"""
Flask extensions - initialized separately to avoid circular imports
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
limiter = Limiter(key_func=get_remote_address)
login_manager = LoginManager()
