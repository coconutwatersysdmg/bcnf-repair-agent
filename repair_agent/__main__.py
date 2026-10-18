import sys
from .cli import main

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,FileExistsError,FileNotFoundError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
