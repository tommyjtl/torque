"""Host authorization policy. The worker can request effects, not grant them."""
MODES = ('auto', 'ask', 'full')
READS = {'read_file', 'list_directory', 'search_files', 'device_snapshot', 'device_capabilities', 'input_capabilities', 'audio_capabilities'}
ROUTINE = {'write_file', 'run_program', 'matrix_fill', 'matrix_draw', 'matrix_clear', 'matrix_release', 'rgb_set'}
FIELDS = {'read_file': {'path'}, 'list_directory': {'path'}, 'search_files': {'path', 'query'},
          'device_snapshot': set(), 'device_capabilities': set(), 'input_capabilities': set(), 'audio_capabilities': set(), 'write_file': {'path', 'content'},
          'run_program': {'path', 'arguments'}, 'shell': {'command'},
          'matrix_fill': {'on'}, 'matrix_draw': {'rows'}, 'matrix_clear': set(), 'matrix_release': set(),
          'rgb_set': {'led', 'red', 'green', 'blue'}}


def mode(value):
    if value not in MODES:
        raise ValueError('Permissions must be auto, ask or full')
    return value


def needs_approval(name, permissions):
    mode(permissions)
    if name not in FIELDS:
        raise ValueError('Unknown host tool')
    return name not in READS and permissions != 'full' and (permissions == 'ask' or name not in ROUTINE)


def validate(name, arguments):
    if name not in FIELDS or not isinstance(arguments, dict) or set(arguments) != FIELDS[name]:
        raise ValueError('Invalid tool arguments')
    if name == 'matrix_fill' and type(arguments['on']) is not bool:
        raise ValueError('Matrix on must be boolean')
    if name == 'matrix_draw':
        from unoq_control import Frame
        if not isinstance(arguments['rows'], list):
            raise ValueError('Matrix rows must be a list')
        Frame.from_rows(arguments['rows'])
    if name == 'rgb_set':
        if type(arguments['led']) is not int or arguments['led'] not in (3, 4):
            raise ValueError('Choose MCU LED 3 or 4')
        if any(type(arguments[key]) is not bool for key in ('red', 'green', 'blue')):
            raise ValueError('RGB channels must be boolean')
    if name in ('read_file', 'list_directory', 'search_files', 'write_file', 'run_program'):
        if not isinstance(arguments['path'], str) or not 0 < len(arguments['path']) <= 4096:
            raise ValueError('Invalid path')
    if name == 'run_program':
        values = arguments['arguments']
        if not isinstance(values, list) or len(values) > 32 or any(not isinstance(v, str) or '\0' in v or len(v) > 4096 for v in values):
            raise ValueError('Program arguments must be a bounded string list')
    if name == 'search_files' and (not isinstance(arguments['query'], str) or not 0 < len(arguments['query']) <= 256):
        raise ValueError('Search needs a literal query of 1..256 characters')
    if name == 'write_file' and (not isinstance(arguments['content'], str) or len(arguments['content'].encode()) > 65536):
        raise ValueError('File exceeds the 64 KiB write limit')
    if name == 'shell' and (not isinstance(arguments['command'], str) or not 0 < len(arguments['command']) <= 16384 or '\0' in arguments['command']):
        raise ValueError('Invalid shell command')
