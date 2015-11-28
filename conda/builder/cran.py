"""
Tools for converting CRAN R packages to conda recipes.
"""
#===============================================================================
# Imports
#===============================================================================
from __future__ import division, absolute_import

import os
import sys
import json

from os.path import join, isdir, exists, isfile

from glob import glob

from conda.fetch import download
from conda.utils import memoize

from collections import defaultdict

from conda.builder.r import (
    r_name_to_conda_name,
    r_version_to_conda_version,

    RPackage,
    CondaRPackage,
    RVersionDependencyMismatch,
)

from pygraph.classes.digraph import digraph
from pygraph.algorithms.searching import (
    depth_first_search,
    breadth_first_search,
)

#===============================================================================
# Globals
#===============================================================================
SITES = {
    'cran': 'http://cran.r-project.org/src/contrib',
    'omegahat': 'http://www.omegahat.org/R/src/contrib',
    'bioconductor': 'http://www.bioconductor.org/packages/release/bioc/src/contrib',
    'bioconductor_annotation': 'http://www.bioconductor.org/packages/release/data/annotation/src/contrib',
}

# The following is used to drive the order of the above dict when order is
# important (like when writing out PACKAGES).
SITE_NAMES = (
    'cran',
    'omegahat',
    'bioconductor',
    'bioconductor_annotation',
)

# ....and just in case we forget to update SITE_NAMES...
assert set(SITE_NAMES) == set(SITES.keys())

#===============================================================================
# Helpers
#===============================================================================
def cran_url_to_src_contrib_url(cran_url):
    trailing_slash = True if cran_url[-1] == '/' else False
    maybe_slash = '/' if not trailing_slash else ''
    suffix = 'src/contrib' + ('/' if trailing_slash else '')
    if not cran_url.endswith(suffix):
        src_contrib_url = cran_url + maybe_slash + suffix
    else:
        src_contrib_url = cran_url + maybe_slash
    return src_contrib_url

def reduce_package_line_continuations(chunk):
    """
    >>> chunk = [
        'Package: A3',
        'Version: 0.9.2',
        'Depends: R (>= 2.15.0), xtable, pbapply',
        'Suggests: randomForest, e1071',
        'Imports: MASS, R.methodsS3 (>= 1.5.2), R.oo (>= 1.15.8), R.utils (>=',
        '        1.27.1), matrixStats (>= 0.8.12), R.filesets (>= 2.3.0), ',
        '        sampleSelection, scatterplot3d, strucchange, systemfit',
        'License: GPL (>= 2)',
        'NeedsCompilation: no']
    >>> reduce_package_line_continuations(chunk)
    ['Package: A3',
     'Version: 0.9.2',
     'Depends: R (>= 2.15.0), xtable, pbapply',
     'Suggests: randomForest, e1071',
     'Imports: MASS, R.methodsS3 (>= 1.5.2), R.oo (>= 1.15.8), R.utils (>= 1.27.1), matrixStats (>= 0.8.12), R.filesets (>= 2.3.0), sampleSelection, scatterplot3d, strucchange, systemfit, rgl,'
     'License: GPL (>= 2)',
     'NeedsCompilation: no']
    """
    continuation = ' ' * 8
    continued_ix = None
    continued_line = None
    had_continuation = False
    accumulating_continuations = False

    for (i, line) in enumerate(chunk):
        if line.startswith(continuation):
            line = ' ' + line.lstrip()
            if accumulating_continuations:
                assert had_continuation
                continued_line += line
                chunk[i] = None
            else:
                accumulating_continuations = True
                continued_ix = i-1
                continued_line = chunk[continued_ix] + line
                had_continuation = True
                chunk[i] = None
        else:
            if accumulating_continuations:
                assert had_continuation
                chunk[continued_ix] = continued_line
                accumulating_continuations = False
                continued_line = None
                continued_ix = None

    if had_continuation:
        # Remove the None(s).
        chunk = [ c for c in chunk if c ]

    chunk.append('')

    return chunk

def convert_dots_to_svg(output_dir):
    from glob import glob
    from subprocess import check_call

    dot_glob = ('/'.join((output_dir, '*.dot'))).replace('//', '/')
    args_fmt = 'dot -Tsvg %s > %s'
    import ipdb
    ipdb.set_trace()
    for f in glob(dot_glob):
        name = f[f.rfind('/')+1:]
        base = name[:name.rfind('.'):]
        svg = base + '.svg'
        args = (args_fmt % (name, svg)).split(' ')
        check_call(args, shell=True)

def download_site_PACKAGES(output_dir):
    paths = []
    for (site, base_url) in SITES.iteritems():
        name = '%s.PACKAGES' % site
        path = join(output_dir, name)
        url = '/'.join((base_url, 'PACKAGES'))
        download(url, path)
        paths.append((site, path))

def finalize_package(lines):
    return '\n'.join(reduce_package_line_continuations(lines))

def strip_crlf(line):
    if line[-2:] == '\r\n':
        line = line[:-2]
    elif line[-1:] == '\n':
        line = line[:-1]
    return line

def update_PACKAGES(output_dir):
    packages = []
    for site in SITE_NAMES:
        name = '%s.PACKAGES' % site
        path = join(output_dir, name)
        site_line = 'Site: %s' % site

        with open(path, 'r') as f:
            chunk = []
            for line in f:
                line = strip_crlf(line)
                if not line:
                    packages.append(finalize_package(chunk))
                    chunk = []
                else:
                    chunk.append(line)
                    if line.startswith('Package:'):
                        chunk.append(site_line)

            if chunk:
                packages.append(finalize_package(chunk))

    with open(join(output_dir, 'PACKAGES'), 'w') as f:
        f.write('\n'.join(packages))

#===============================================================================
# CRAN Task View Helpers
#===============================================================================
CRAN_VIEWS_RDS_NAME = 'cran.Views.rds'
CRAN_VIEWS_JSON_NAME = 'cran.Views.json'

def download_cran_task_views_rds(output_dir):
    url = '/'.join((SITES['cran'], 'Views.rds'))
    path = join(output_dir, CRAN_VIEWS_RDS_NAME)
    download(url, path)

def cran_task_view_name_to_conda_name(ctv_name, core_or_full):
    suffix = '' if core_or_full == 'full' else '-core'
    return 'r-view-%s%s' % (ctv_name.lower(), suffix)

def views_rds_to_dict(views):
    r = {}

    for rv in views:
        f = {}
        c = {}

        name = rv[0][0]
        f['name'] = cran_task_view_name_to_conda_name(name, 'full')
        c['name'] = cran_task_view_name_to_conda_name(name, 'core')

        version = r_version_to_conda_version(rv[4][0])
        f['version'] = version
        c['version'] = version

        names = rv[5][0]
        cores = rv[5][1]

        f['depends'] = []
        c['depends'] = []

        for (r_name, is_core) in zip(names, cores):
            conda_name = r_name_to_conda_name(r_name)

            if is_core:
                c['depends'].append(conda_name)

            f['depends'].append(conda_name)

        r[f['name']] = f
        r[c['name']] = c

    return r

def convert_views_rds_to_json(output_dir):
    rds_path = join(output_dir, CRAN_VIEWS_RDS_NAME)
    json_path = join(output_dir, CRAN_VIEWS_JSON_NAME)

    download_cran_task_views_rds(output_dir)

    import rpy2.robjects as ro
    rviews = ro.r("v <- readRDS('%s')" % rds_path)
    views = views_rds_to_dict(rviews)

    with open(json_path, 'w') as f:
        json.dump(views, f, indent=2, sort_keys=True)

def load_views_from_json(output_dir):
    with open(join(output_dir, CRAN_VIEWS_JSON_NAME), 'r') as f:
        return json.load(f)

class CondaCranTaskViewPackage(CondaRPackage):
    def __init__(self, output_dir, **kwds):
        for slot in RPackage.__slots__:
            setattr(self, slot, '')

        self.output_dir = output_dir

        # Ugh, there's unnecessary code duplication between our __init__ and
        # RPackage's __init__; the latter really needs to be refactored to
        # better support the needs of view-only packages.  Let's just do
        # something quick and dirty for now.
        self.is_view = True
        self.conda_name = kwds['name']
        self.conda_version = kwds['version']
        self.conda_depends = kwds['depends']

        self.path = join(output_dir, self.conda_name)

        self.meta_yaml = None
        self.meta_path = join(self.path, 'meta.yaml')

        self._determine_build_number()

        self.conda_build = str(self.conda_build_number)
        self.conda_build_tarball = (
            '%s-%s-%d.tar.bz2' % (
                self.conda_name,
                self.conda_version,
                self.conda_build_number,
            )
        )

        self.cran = kwds
        self.conda_reverse_depends = []
        self.conda_unsatisfied_depends = []

#===============================================================================
# Classes
#===============================================================================

class CranPackages(object):
    # I'm currently using this class in an exploratory-development fashion via
    # an interactive IPython session. It'll eventually be hooked into the CLI.

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.packages_file = join(output_dir, 'PACKAGES')
        self.repodata_json = join(output_dir, 'repodata.json')
        self.builddata_json = join(output_dir, 'builddata.json')

        # A dict of CondaRPackage instances keyed by conda package name.
        self.rpackages = {}

        # A dict keyed by build tarball filename, values are dicts
        # representing the repodata format of a conda package.
        self.packages = {}

        # A dict of dicts, keyed by conda package name for views.  Each inner
        # dict will have the minimal set of view keys (name, version, depends).
        # This is loaded straight from the views json during the _load_views()
        # step.
        self.views = {}

        # A dict of CondaCranTaskViewPackage instances keyed by conda package
        # names.  These will be generated by the _load_views() call (which is
        # called by _load_packages() after it's finished loading normal
        # packages).
        self.rviews = {}

        # Keep track of package names in self.nodes; when loading packages, we
        # only add a node to the graph if the name isn't present in self.nodes.
        self.nodes = set()
        self.digraph = digraph()

        # ....and let's just disable graphing for now -- it's conflicting with
        # the new view functionality, and we don't even use it for anything
        # important anyway.
        self.build_graph = False

        # Keep track of packages that have no other dependencies (other than
        # a dependency on R, which all packages will have).
        self.no_other_dependencies = set()

        self.unknown_packages = defaultdict(list)
        self.packages_with_unsatisfied_dependencies = {}
        self.packages_removed = list()

        self._read_packages_file()

    def write_recipes(self):
        self._load_packages()

        for rpkg in self.rpackages.itervalues():
            rpkg.write_recipe()

    def _write_repodata_json(self):
        self._load_packages()

        with open(self.repodata_json, 'w') as f:
            repodata = {
                'info': { },
                'packages': self.packages,
            }
            json.dump(repodata, f, indent=2, sort_keys=True)

    def _write_builddata_json(self):
        with open(self.builddata_json, 'w') as f:
            builddata = {
                name: rpkg._to_builddata_dict()
                    for (name, rpkg) in self.rpackages.iteritems()
            }
            json.dump(builddata, f, indent=2, sort_keys=True)

    def write_graphs_to_dots(self):
        assert self.build_graph
        self._load_packages()

        from pygraph.readwrite import dot

        base = self.output_dir

        with open(join(base, 'digraph.dot'), 'w') as f:
            data = dot.write(self.digraph)
            f.write(data)

        with open(join(base, 'bfs.dot'), 'w') as f:
            (st, order) = breadth_first_search(self.digraph)
            bfs = digraph()
            bfs.add_spanning_tree(st)
            data = dot.write(bfs)
            f.write(data)

        with open(join(base, 'dfs.dot'), 'w') as f:
            (st, pre, post) = depth_first_search(self.digraph)
            dfs = digraph()
            dfs.add_spanning_tree(st)
            data = dot.write(dfs)
            f.write(data)

    def _read_packages_file(self):
        with open(self.packages_file, 'r') as f:
            data = f.read()
        lines = data.splitlines()
        chunk = []
        chunks = []
        for line in lines:
            if not line:
                chunks.append(reduce_package_line_continuations(chunk))
                chunk = []
            else:
                chunk.append(line)

        self.lines = lines
        self.chunks = chunks

    def _load_packages(self):
        if self.rpackages:
            return
        output_dir = self.output_dir
        r_names_seen = set()
        conda_names_seen = set()
        for lines in self.chunks:
            site = lines[1].split(': ')[1]
            base_url = SITES[site]
            try:
                rpkg = CondaRPackage(lines, base_url, output_dir)
            except RVersionDependencyMismatch:
                # The package depends on a version of R different from ours.
                # (We'll eventually handle this via conda version management;
                # much like we do for multiple Python versions/dependencies.)
                continue

            # Make sure the package name is unique in both the R universe
            # and our conda universe.
            r_name = rpkg.package
            conda_name = rpkg.conda_name

            if r_name in r_names_seen:
                # Ugh, just leave the first one for now.
                print "warning: ignoring duplicate package: %s" % r_name
                continue

            assert r_name not in r_names_seen, r_name
            assert conda_name not in conda_names_seen, conda_name

            r_names_seen.add(r_name)
            conda_names_seen.add(conda_name)

            self._save_package(rpkg)

        self._load_views()

    def _save_package(self, rpkg):
        conda_name = rpkg.conda_name
        assert conda_name not in self.rpackages, conda_name

        # Add to our list of rpackages.
        self.rpackages[conda_name] = rpkg

        # And the repodata/index dict.
        fn = rpkg.conda_build_tarball
        d = rpkg._to_repodata_dict()
        assert fn not in self.packages, fn
        self.packages[fn] = d

    def _load_views(self):
        if self.views:
            assert self.rviews
            return

        assert not self.rviews
        self.views = load_views_from_json(self.output_dir)

        for view in self.views.itervalues():
            rpkg = CondaCranTaskViewPackage(self.output_dir, **view)
            self.rviews[rpkg.conda_name] = rpkg

            self._save_package(rpkg)

    def _process_packages(self):
        self._load_packages()

        for rpkg in self.rpackages.itervalues():
            self._process_package(rpkg)

        self._process_unsatisfied_packages()
        self._write_repodata_json()
        self._write_builddata_json()

    def _process_package(self, rpkg):
        name = rpkg.conda_name

        if name not in self.nodes:
            self.nodes.add(name)
            if self.build_graph:
                self.digraph.add_nodes([name,])

        for dependency in rpkg.conda_depends:
            if dependency not in self.nodes:
                self.nodes.add(dependency)
                if self.build_graph:
                    self.digraph.add_nodes([dependency,])

            if self.build_graph:
                self.digraph.add_edge((name, dependency))

            if dependency == 'r':
                continue

            if dependency not in self.rpackages:
                if not isdir(join(self.output_dir, dependency)):
                    self.unknown_packages[dependency].append(rpkg)
                    self.packages_with_unsatisfied_dependencies[name] = rpkg
                    rpkg.conda_unsatisfied_depends.append(dependency)
                continue

            # Don't track reverse dependencies for views.
            dpkg = self.rpackages[dependency]
            if not dpkg.is_view:
                dpkg.conda_reverse_depends.append(name)

        # Note of packages that have no dependencies other than R.
        if not rpkg.is_view and rpkg.conda_depends == ['r',]:
            self.no_other_dependencies.add(name)

    def _process_unsatisfied_packages(self):

        for (dependency, rpackages) in self.unknown_packages.iteritems():
            for rpkg in rpackages:
                self._process_unsatisfied_package(rpkg, dependency)

        # Verify all packages now have valid dependencies.
        for rpkg in self.rpackages.itervalues():
            for depname in rpkg.conda_depends:
                if depname == 'r':
                    continue
                assert depname in self.rpackages

        for name in self.packages_removed:
            path = join(self.output_dir, name)
            if isdir(path):
                msg = "no references to package directory: %s\n" % path

    def _process_unsatisfied_package(self, rpkg, dependency):
        name = rpkg.conda_name

        if name in self.rpackages:
            msg = (
                "removing package: %s "
                "(can't satisfy dependency: %s)\n"
            ) % (name, dependency)
            sys.stdout.write(msg)
            del self.rpackages[name]
            del self.packages[rpkg.conda_build_tarball]
            self.packages_removed.append(name)

        for depname in rpkg.conda_reverse_depends:
            rpkg = self.rpackages.get(depname)
            if rpkg:
                self._process_unsatisfied_package(rpkg, depname)

    def _find_unique_package_description_keys(self):
        """
        Helper method that enumerates all lines in PACKAGES and finds the
        unique keys used to describe packages.  i.e. given:

            ['Package: A3',
             'Version: 0.9.2',
             'Depends: R (>= 2.15.0), xtable, pbapply',
             'Suggests: randomForest, e1071',
             'License: GPL (>= 2)',
             'NeedsCompilation: no']

        This will return 'Package', 'Version', etc.
        """
        seen = set()
        for chunk in self.chunks:
            for line in chunk:
                if not line:
                    continue
                (key, value) = line.split(': ')
                seen.add(key)

        return sorted(seen)


#===============================================================================
# Main
#===============================================================================
def main(args, parser):
    pass

# vim:set ts=8 sw=4 sts=4 tw=78 et:
