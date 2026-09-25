import sys
sys.path.append('/code')
from app.security import hash_password
from app.database import engine
from sqlalchemy import text

new_hash = hash_password('admin123')
with engine.begin() as conn:
    conn.execute(text("UPDATE usuario SET password_hash = :hash WHERE email = 'brandocaracas@gmail.com'"), {'hash': new_hash})
print("Password updated correctly.")
