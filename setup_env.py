"""Create private configuration without placing real secrets in the repository."""
import os
from pathlib import Path
import secrets

path = Path(__file__).with_name('.env')
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('.env already exists; left unchanged.')
with os.fdopen(fd, 'w') as output:
    output.write(f'SECRET_KEY={secrets.token_hex(32)}\nPOSTGRES_PASSWORD={secrets.token_hex(24)}\nPORT=80\nCOOKIE_SECURE=false\n')
print('Created .env with random application and database secrets.')
