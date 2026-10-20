import sys
from pathlib import Path
from getpass import getpass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import make_password_hash
print(make_password_hash(getpass("Пароль: ")))
