from __future__ import print_function, division, absolute_import

import os
import sys
import json
import stat
import shutil
import tarfile
from os.path import exists, isdir, islink, join
import subprocess

import conda.config as cc
import conda.plan as plan
from conda.utils import url_path
from conda.api import get_index
from conda.install import prefix_placeholder

from conda.builder import config
from conda.fetch import fetch_index
from conda.builder import environ
from conda.builder import source
from conda.builder import tarcheck
from conda.builder.scripts import create_entry_points, bin_dirname
from conda.builder.post import (post_process, post_build, is_obj,
                                fix_permissions)
from conda.builder.utils import rm_rf, _check_call
from conda.builder.index import update_index
from conda.builder.create_test import create_files


prefix = config.build_prefix
info_dir = join(prefix, 'info')
bldpkgs_dir = join(config.croot, cc.subdir)
broken_dir = join(config.croot, "broken")

def prefix_files():
    res = set()
    for root, dirs, files in os.walk(prefix):
        for fn in files:
            res.add(join(root, fn)[len(prefix) + 1:])
        for dn in dirs:
            path = join(root, dn)
            if islink(path):
                res.add(path[len(prefix) + 1:])
    return res


def have_prefix_files(files):
    for f in files:
        if f.endswith(('.pyc', '.pyo', '.a')):
            continue
        path = join(prefix, f)
        if isdir(path):
            continue
        if sys.platform != 'darwin' and islink(path):
            # OSX does not allow hard-linking symbolic links, so we cannot
            # skip symbolic links (as we can on Linux)
            continue
        if is_obj(path):
            continue
        if islink(path):
            continue
        try:
            with open(path) as fi:
                data = fi.read()
        except UnicodeDecodeError:
            continue
        if prefix not in data:
            continue
        st = os.stat(path)
        data = data.replace(prefix, prefix_placeholder)
        with open(path, 'w') as fo:
            fo.write(data)
        os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR) # chmod u+w
        yield f


def create_info_files(m, files):
    recipe_dir = join(info_dir, 'recipe')
    os.makedirs(recipe_dir)

    for fn in os.listdir(m.path):
        if fn.startswith('.'):
            continue
        src_path = join(m.path, fn)
        dst_path = join(recipe_dir, fn)
        if isdir(src_path):
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy(src_path, dst_path)

    with open(join(info_dir, 'files'), 'w') as fo:
        for f in files:
            if sys.platform == 'win32':
                f = f.replace('\\', '/')
            fo.write(f + '\n')

    with open(join(info_dir, 'index.json'), 'w') as fo:
        json.dump(m.info_index(), fo, indent=2, sort_keys=True)

    with open(join(info_dir, 'recipe.json'), 'w') as fo:
        json.dump(m.meta, fo, indent=2, sort_keys=True)

    if sys.platform != 'win32':
        prefix_files = list(have_prefix_files(files))
        if prefix_files:
            with open(join(info_dir, 'has_prefix'), 'w') as fo:
                for f in prefix_files:
                    fo.write(f + '\n')

    if m.get_value('source/git_url'):
        with open(join(info_dir, 'git'), 'w') as fo:
            source.git_info(fo)

    if m.get_value('app/icon'):
        shutil.copyfile(join(m.path, m.get_value('app/icon')),
                        join(info_dir, 'icon.png'))


def create_env(pref, specs, pypi=False):
    if not isdir(bldpkgs_dir):
        os.makedirs(bldpkgs_dir)
    update_index(bldpkgs_dir)
    # remove the cache such that a refetch is made,
    # this is necessary because we add the local build repo URL
    fetch_index.cache = {}
    index = get_index([url_path(config.croot)])

    cc.pkgs_dirs = cc.pkgs_dirs[:1]

    if pypi:
        from conda.from_pypi import install_from_pypi
        specs = install_from_pypi(pref, index, specs)

    actions = plan.install_actions(pref, index, specs)
    plan.display_actions(actions, index)
    plan.execute_actions(actions, index, verbose=True)
    # ensure prefix exists, even if empty, i.e. when specs are empty
    if not isdir(pref):
        os.makedirs(pref)

def rm_pkgs_cache(dist):
    cc.pkgs_dirs = cc.pkgs_dirs[:1]
    rmplan = ['RM_FETCHED %s' % dist,
              'RM_EXTRACTED %s' % dist]
    plan.execute_plan(rmplan)

def bldpkg_path(m):
    return join(bldpkgs_dir, '%s.tar.bz2' % m.dist())


def build(m, get_src=True, pypi=False):
    rm_rf(prefix)
    create_env(prefix, [ms.spec for ms in m.ms_depends('build')], pypi)

    print("BUILD START:", m.dist())

    if get_src:
        source.provide(m.path, m.get_section('source'))
    assert isdir(source.WORK_DIR)
    if os.listdir(source.get_dir()):
        print("source tree in:", source.get_dir())
    else:
        print("no source")

    rm_rf(info_dir)
    files1 = prefix_files()

    if sys.platform == 'win32':
        import conda.builder.windows as windows
        windows.build(m)
    else:
        build_sh = join(m.path, 'build.sh')
        if exists(build_sh):
            env = environ.get_dict(m)
            cmd = ['/bin/bash', '-x', '-e', build_sh]
            _check_call(cmd, env=env, cwd=source.get_dir())
        else:
            print("no build.sh file")

    create_entry_points(m.get_value('build/entry_points'))
    post_process(preserve_egg_dir=bool(
            m.get_value('build/preserve_egg_dir')))

    assert not exists(info_dir)
    files2 = prefix_files()

    post_build(sorted(files2 - files1))
    create_info_files(m, sorted(files2 - files1))
    files3 = prefix_files()
    fix_permissions(files3 - files1)

    path = bldpkg_path(m)
    t = tarfile.open(path, 'w:bz2')
    for f in sorted(files3 - files1):
        t.add(join(prefix, f), f)
    t.close()

    print("BUILD END:", m.dist())

    # we're done building, perform some checks
    tarcheck.check_all(path)
    update_index(bldpkgs_dir)


def test(m, pypi=False):
    # remove from package cache
    rm_pkgs_cache(m.dist())

    tmp_dir = join(config.croot, 'test-tmp_dir')
    rm_rf(tmp_dir)
    os.makedirs(tmp_dir)
    if not create_files(tmp_dir, m):
        print("Nothing to test for:", m.dist())
        return

    print("TEST START:", m.dist())
    rm_rf(prefix)
    rm_rf(config.test_prefix)
    specs = ['%s %s %s' % (m.name(), m.version(), m.build_id()),
             # as the tests are run by python, we need to specify it
             'python %s*' % environ.py_ver]
    # add packages listed in test/requires
    for spec in m.get_value('test/requires'):
        specs.append(spec)

    create_env(config.test_prefix, specs, pypi)

    env = dict(os.environ)
    # prepend bin (or Scripts) directory
    env['PATH'] = (join(config.test_prefix, bin_dirname) + os.pathsep +
                   env['PATH'])

    for varname in 'CONDA_PY', 'CONDA_NPY':
        env[varname] = str(getattr(config, varname))
    env['PREFIX'] = config.test_prefix

    try:
        subprocess.check_call([config.test_python, join(tmp_dir, 'run_test.py')],
            env=env, cwd=tmp_dir)
    except subprocess.CalledProcessError:
        if not isdir(broken_dir):
            os.makedirs(broken_dir)
        shutil.move(bldpkg_path(m), join(broken_dir, "%s.tar.bz2" % m.dist()))
        sys.exit("TESTS FAILED: " + m.dist())

    print("TEST END:", m.dist())
