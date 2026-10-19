"""Standard-library-only bootstrap for Python 3.12, including official NuGet Python."""
from pathlib import Path
import os
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent

class SetupError(Exception):
    pass

def environment_python(directory, platform=None):
    """Join using the supplied path flavor; do not mutate global os.name."""
    platform = os.name if platform is None else platform
    return directory / ('Scripts/python.exe' if platform == 'nt' else 'bin/python')

def checked(args, **kwargs):
    result = subprocess.run([str(arg) for arg in args], **kwargs)
    if result.returncode:
        raise SetupError('Setup command failed (exit '+str(result.returncode)+'). Read the error above; no bot was started.')
    return result

def prepare(root=ROOT):
    if sys.version_info[:2] != (3, 12):
        raise SetupError('Python 3.12 is required. Set KALSHI_PYTHON to the full path of your Python 3.12 python.exe.')
    root = Path(root).resolve()
    directory = root / '.venv'
    python = environment_python(directory)
    print('Using Python '+sys.version.split()[0]+': '+sys.executable, flush=True)
    if not python.is_file():
        if directory.exists():
            raise SetupError('An incomplete .venv already exists. Keep your data folder; rename .venv to .venv-old and retry. Nothing was deleted.')
        print('Creating a private project environment (first launch only)...', flush=True)
        try:
            venv.EnvBuilder(with_pip=True).create(directory)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SetupError('Could not create .venv. Keep the entire NuGet tools folder, not just python.exe. '+str(exc)) from None
    # Use an isolated probe so another PYTHONPATH cannot silently supply packages.
    result = checked([python, '-I', '-c',
                      'import sys; print("%d.%d" % sys.version_info[:2])'],
                     capture_output=True, text=True)
    if result.stdout.strip() != '3.12':
        raise SetupError('Existing .venv uses a different Python version. Rename .venv to .venv-old and retry; keep data unchanged.')
    pip = subprocess.run([str(python), '-I', '-m', 'pip', '--version'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if pip.returncode:
        print('Restoring pip from the Python distribution...', flush=True)
        checked([python, '-I', '-m', 'ensurepip', '--upgrade'])
    print('Installing/verifying project dependencies...', flush=True)
    checked([python, '-I', '-m', 'pip', 'install', '--disable-pip-version-check',
             '-r', root/'requirements.txt'], cwd=root)
    checked([python, '-I', '-m', 'pip', 'check'], cwd=root)
    # Import real application modules without executing the scanner or Telegram.
    checked([python, '-c', 'import scanner, dashboard, waitress; print("Scanner and dashboard imports: OK")'], cwd=root)
    return python

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ['--setup-only']):
        print('Usage: windows_setup.py [--setup-only]');return 2
    try:
        python = prepare()
        if args:
            print('Setup complete. No scanner or Telegram messages started.');return 0
        # private_setup keeps credentials in memory and starts the existing local runner.
        return subprocess.call([str(python), str(ROOT/'private_setup.py')], cwd=ROOT)
    except (SetupError, OSError) as exc:
        print('Setup failed: '+str(exc));return 1
    except KeyboardInterrupt:
        print('\nSetup cancelled.');return 130

if __name__ == '__main__':
    sys.exit(main())
