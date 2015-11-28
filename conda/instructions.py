from logging import getLogger

from conda import config
from conda import install
from conda.exceptions import InvalidInstruction
from conda.fetch import fetch_pkg

log = getLogger(__name__)

# op codes
FETCH = 'FETCH'
EXTRACT = 'EXTRACT'
UNLINK = 'UNLINK'
LINK = 'LINK'
RM_EXTRACTED = 'RM_EXTRACTED'
RM_FETCHED = 'RM_FETCHED'
PREFIX = 'PREFIX'
PRINT = 'PRINT'
PROGRESS = 'PROGRESS'
SYMLINK_CONDA = 'SYMLINK_CONDA'


progress_cmds = set([EXTRACT, RM_EXTRACTED, LINK, UNLINK])
action_codes = (
    FETCH,
    EXTRACT,
    UNLINK,
    LINK,
    SYMLINK_CONDA,
    RM_EXTRACTED,
    RM_FETCHED,
)


def PREFIX_CMD(state, arg):
    state['prefix'] = arg


def PRINT_CMD(state, arg):
    getLogger('print').info(arg)


def fetch(index, dist):
    assert index is not None
    fn = dist + '.tar.bz2'
    fetch_pkg(index[fn])


def FETCH_CMD(state, dist):
    fetch(state['index'], dist)


def PROGRESS_CMD(state, maxval):
    state['i'] = 0
    state['maxval'] = maxval
    getLogger('progress.start').info(maxval)


def EXTRACT_CMD(state, dist):
    install.extract(config.pkgs_dirs[0], dist)


def RM_EXTRACTED_CMD(state, dist):
    install.rm_extracted(config.pkgs_dirs[0], dist)


def RM_FETCHED_CMD(state, dist):
    install.rm_fetched(config.pkgs_dirs[0], dist)


def split_linkarg(args):
    "Return tuple(dist, pkgs_dir, linktype)"
    if not isinstance(args, (list, tuple)):
        args = (args,)
    return _split_linkarg(*args)
<<<<<<< HEAD
<<<<<<< HEAD

=======
>>>>>>> origin/feature/instruction-arguments

def _split_linkarg(dist, pkgs_dir=config.pkgs_dirs[0], linktype=install.LINK_HARD):
    return dist, pkgs_dir, linktype

<<<<<<< HEAD

def LINK_CMD(state, dist, pkgs_dir=config.pkgs_dirs[0], lt=install.LINK_HARD):
    prefix = state['prefix']
    index = state['index']
    install.link(pkgs_dir, prefix, dist, lt, index=index)


def UNLINK_CMD(state, dist):
    install.unlink(state['prefix'], dist)
=======
def _split_linkarg(dist, pkgs_dir=config.pkgs_dirs[0], linktype=install.LINK_HARD):
    return dist, pkgs_dir, linktype

=======


def _split_linkarg(dist, pkgs_dir=config.pkgs_dirs[0], linktype=install.LINK_HARD):
    return dist, pkgs_dir, linktype
>>>>>>> conda/feature/instruction-arguments

def LINK_CMD(state, dist, pkgs_dir=config.pkgs_dirs[0], lt=install.LINK_HARD):
    prefix = state['prefix']
    index = state['index']
    install.link(pkgs_dir, prefix, dist, lt, index=index)

<<<<<<< HEAD
>>>>>>> origin/feature/instruction-arguments

def UNLINK_CMD(state, dist):
    install.unlink(state['prefix'], dist)


def SYMLINK_CONDA_CMD(state, root_dir):
    install.symlink_conda(state['prefix'], root_dir)

<<<<<<< HEAD
def SYMLINK_CONDA_CMD(state, root_dir):
    install.symlink_conda(state['prefix'], root_dir)

=======
>>>>>>> origin/feature/instruction-arguments
=======
def LINK_CMD(state, dist, pkgs_dir=config.pkgs_dirs[0], lt=install.LINK_HARD):
    prefix = state['prefix']
    index = state['index']
    install.link(pkgs_dir, prefix, dist, lt, index=index)


def UNLINK_CMD(state, dist):
    install.unlink(state['prefix'], dist)


def SYMLINK_CONDA_CMD(state, root_dir):
    install.symlink_conda(state['prefix'], root_dir)

>>>>>>> conda/feature/instruction-arguments

# Map instruction to command (a python function)
commands = {
    PREFIX: PREFIX_CMD,
    PRINT: PRINT_CMD,
    FETCH: FETCH_CMD,
    PROGRESS: PROGRESS_CMD,
    EXTRACT: EXTRACT_CMD,
    RM_EXTRACTED: RM_EXTRACTED_CMD,
    RM_FETCHED: RM_FETCHED_CMD,
    LINK: LINK_CMD,
    UNLINK: UNLINK_CMD,
    SYMLINK_CONDA: SYMLINK_CONDA_CMD,
}


def execute_instructions(plan, index=None, verbose=False, _commands=None):
    """
    Execute the instructions in the plan

    :param plan: A list of (instruction, arg) tuples
    :param index: The meta-data index
    :param verbose: verbose output
    :param _commands: (For testing only) dict mapping an instruction to executable if None
    then the default commands will be used
    """
    if _commands is None:
        _commands = commands

    if verbose:
        from conda.console import setup_verbose_handlers
        setup_verbose_handlers()

    state = {'i': None, 'prefix': config.root_dir, 'index': index}

    for instruction, args in plan:

        if not isinstance(args, (list, tuple)):
            args = (args,)

        log.debug(' %s%r' % (instruction, args))

        if state['i'] is not None and instruction in progress_cmds:
            state['i'] += 1
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
            getLogger('progress.update').info((install.name_dist(arg),
                state['i']-1))
        cmd = _commands.get(instruction)
=======
=======
>>>>>>> origin/feature/instruction-arguments
=======
>>>>>>> conda/feature/instruction-arguments
            getLogger('progress.update').info((args[0], state['i']))

        cmd = commands.get(instruction)
>>>>>>> conda/feature/instruction-arguments

        if cmd is None:
            raise InvalidInstruction(instruction)

        cmd(state, *args)

        if (state['i'] is not None and instruction in progress_cmds
                and state['maxval'] == state['i']):
            state['i'] = None
            getLogger('progress.stop').info(None)

    install.messages(state['prefix'])
