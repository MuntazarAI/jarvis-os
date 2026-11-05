#!/usr/bin/env python3
"""
Sandbox wrapper - runs user code with import/builtin restrictions.
"""
import sys
import builtins
import importlib
import json
import os
import socket

# Policy placeholders - will be replaced by the generator
ALLOWED_IMPORTS = __ALLOWED_IMPORTS__
BLOCKED_IMPORTS = __BLOCKED_IMPORTS__
ALLOWED_BUILTINS = __ALLOWED_BUILTINS__
SANDBOX_DIR = __SANDBOX_DIR__

# Pre-load essential modules BEFORE applying import restrictions
# This allows internal modules (statistics, datetime, etc.) to work
_essential_modules = ['sys', 'io', 'json', 'collections', 'math', 'random', 'datetime', 'time']
for _mod_name in _essential_modules:
    try:
        importlib.import_module(_mod_name)
    except ImportError:
        pass

# Capture original imports BEFORE applying restrictions
_original_import = builtins.__import__
_original_open = open
_original_socket = socket.socket

# Disable network FIRST (before import restrictions)
def _blocked_socket(*args, **kwargs):
    raise PermissionError("Network access blocked by sandbox")
socket.socket = _blocked_socket

# Restrict imports
_original_import = builtins.__import__

def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    # Check blocked list FIRST
    if name in BLOCKED_IMPORTS:
        raise ImportError(f"Import of '{name}' is blocked by sandbox policy")
    # Allow already-loaded modules
    if name in sys.modules:
        return sys.modules[name]
    if name not in ALLOWED_IMPORTS:
        # Check parent package
        parent = name.split('.')[0]
        if parent not in ALLOWED_IMPORTS:
            raise ImportError(f"Import of '{name}' not in allowlist")
    return _original_import(name, globals, locals, fromlist, level)

builtins.__import__ = _restricted_import

# Restrict builtins
original_builtins = dict(builtins.__dict__)
for key in list(builtins.__dict__.keys()):
    if key not in ALLOWED_BUILTINS and not key.startswith('_'):
        delattr(builtins, key)

# Restrict os module if present
if 'os' in sys.modules:
    os_mod = sys.modules['os']
    dangerous_attrs = ['system', 'popen', 'spawn', 'exec', 'fork', 'kill',
                       'remove', 'rmdir', 'unlink', 'rename', 'mkdir',
                       'chdir', 'chmod', 'chown', 'access']
    for attr in dangerous_attrs:
        if hasattr(os_mod, attr):
            setattr(os_mod, attr, lambda *a, **k: (_ for _ in ()).throw(
                PermissionError(f"os.{attr} blocked")))

# Disable network
_original_socket = socket.socket
def _blocked_socket(*args, **kwargs):
    raise PermissionError("Network access blocked by sandbox")
socket.socket = _blocked_socket

# Track files written during execution for artifact capture
_written_files = set()

# Filesystem restriction - restrict open to sandbox directory
_original_open = open
def _restricted_open(file, mode='r', *args, **kwargs):
    # Resolve the path
    if not isinstance(file, (str, bytes, os.PathLike)):
        raise TypeError("file must be str, bytes, or os.PathLike")
    filepath = os.path.abspath(os.path.expanduser(file))
    sandbox_path = os.path.abspath(SANDBOX_DIR)
    
    # Check if path is within sandbox directory
    if not filepath.startswith(sandbox_path):
        raise PermissionError(f"Access to '{file}' denied: outside sandbox directory")
    
    # Track files opened for writing
    if 'w' in mode or 'a' in mode or '+' in mode:
        _written_files.add(filepath)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    return _original_open(file, mode, *args, **kwargs)

builtins.open = _restricted_open

# Restrict builtins
original_builtins = dict(builtins.__dict__)
for key in list(builtins.__dict__.keys()):
    if key not in ALLOWED_BUILTINS and not key.startswith('_'):
        delattr(builtins, key)

# Restrict os module if present
if 'os' in sys.modules:
    os_mod = sys.modules['os']
    dangerous_attrs = ['system', 'popen', 'spawn', 'exec', 'fork', 'kill',
                       'remove', 'rmdir', 'unlink', 'rename', 'mkdir',
                       'chdir', 'chmod', 'chown', 'access']
    for attr in dangerous_attrs:
        if hasattr(os_mod, attr):
            setattr(os_mod, attr, lambda *a, **k: (_ for _ in ()).throw(
                PermissionError(f"os.{attr} blocked")))

# Disable network
_original_socket = socket.socket
def _blocked_socket(*args, **kwargs):
    raise PermissionError("Network access blocked by sandbox")
socket.socket = _blocked_socket

# Execute user code
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    code_file = sys.argv[1]
    with open(code_file, 'r') as f:
        user_code = f.read()

    # Create restricted globals
    restricted_globals = {
        '__builtins__': builtins,
        '__name__': '__main__',
        '__file__': code_file,
    }

    try:
        exec(user_code, restricted_globals)
        # Capture return value if any
        __result_val = restricted_globals.get('__result__', None)
        if __result_val is not None:
            print("__RESULT__:" + json.dumps(__result_val, default=str))
        # Capture written files as artifacts
        import base64
        for filepath in sorted(_written_files):
            try:
                with open(filepath, 'rb') as f:
                    content = f.read()
                b64 = base64.b64encode(content).decode('ascii')
                print(f"__ARTIFACT__:{os.path.basename(filepath)}:{b64}")
            except:
                pass
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        print("__ERROR__:" + type(e).__name__ + ":" + str(e), file=sys.stderr)
        sys.exit(1)