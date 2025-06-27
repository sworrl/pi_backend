#
# pi_backend/security_manager.py
#

# ==============================================================================
# Version: 1.2.1 (Argon2 Password Verification)
#
# Changelog:
# - Version 1.1.0: Corrected class name from Security_Manager to SecurityManager
#   to resolve the ImportError in app.py.
# - Version 1.2.0: Integrated user authentication (verify_credentials) and
#   role-based authorization (get_user_role, is_admin) directly into this class,
#   removing dependency on a non-existent PermissionEnforcer class.
#   Now interacts with DatabaseManager for user data.
# - Version 1.2.1: Updated `verify_credentials` to use Argon2 for secure
#   password verification, replacing the insecure direct string comparison.
#   Requires 'argon2-cffi' library.
# - Version 1.0.0: Initial implementation.
# ==============================================================================

import logging

# Import Argon2 for password verification
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    PH = PasswordHasher()
    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False
    logging.critical("SecurityManager: CRITICAL ERROR: 'argon2-cffi' not found. Password verification will be insecure.")
    # Dummy verifier for basic functionality, but WARN severely
    class DummyPasswordHasher:
        def verify(self, hashed_password, password):
            logging.warning("SecurityManager: Using insecure dummy verification (Argon2 not available).")
            return hashed_password == password # Direct comparison - DANGER!
    PH = DummyPasswordHasher()
except Exception as e:
    ARGON2_AVAILABLE = False
    logging.critical(f"SecurityManager: CRITICAL ERROR: Failed to initialize Argon2 PasswordHasher: {e}")
    PH = DummyPasswordHasher()


# Configure logging for this module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SecurityManager:
    """
    Manages authentication and authorization for the application.
    Interacts with the DatabaseManager for user credentials and roles.
    """
    def __init__(self, db_manager):
        """
        Initializes the SecurityManager.

        Args:
            db_manager (DatabaseManager): An instance of the application's DatabaseManager.
        """
        self.db_manager = db_manager
        logging.info("SecurityManager initialized.")

    def verify_credentials(self, username, password):
        """
        Verifies user credentials against the database using Argon2 hashing.
        
        Args:
            username (str): The username to verify.
            password (str): The plaintext password to verify.

        Returns:
            bool: True if credentials are valid, False otherwise.
        """
        user_record = self.db_manager.get_user_with_hash(username)
        
        if user_record:
            if not ARGON2_AVAILABLE:
                logging.error("Argon2 not available. Cannot securely verify credentials.")
                return False # Or fallback to dummy, but better to fail securely

            try:
                PH.verify(user_record['password_hash'], password)
                logging.info(f"Credentials valid for user: {username}")
                return True
            except VerifyMismatchError:
                logging.warning(f"Invalid password for user: {username} (Argon2 mismatch).")
                return False
            except Exception as e:
                logging.error(f"Error during password verification for user '{username}': {e}")
                return False
        else:
            logging.warning(f"User not found: {username}")
        return False

    def get_user_role(self, username):
        """
        Retrieves the role of a given user from the database.

        Args:
            username (str): The username whose role is to be retrieved.

        Returns:
            str: The user's role ('admin', 'user', etc.) or None if not found.
        """
        user_record = self.db_manager.get_user(username) # Use get_user (without hash)
        if user_record:
            return user_record['role']
        return None

    def is_admin(self, username):
        """
        Checks if a user has the 'admin' role.

        Args:
            username (str): The username to check.

        Returns:
            bool: True if the user is an admin, False otherwise.
        """
        role = self.get_user_role(username)
        return role == 'admin'

    def authenticate(self, api_key):
        """
        (Original method, kept for compatibility if used elsewhere)
        Authenticates a request using the provided API key.
        This method is separate from user/password authentication.

        Args:
            api_key (str): The API key from the request.

        Returns:
            bool: True if the API key is valid, False otherwise.
        """
        logging.warning("SecurityManager.authenticate(api_key) called. This method's implementation might be incomplete/deprecated depending on app's API key strategy.")
        return False # Default to false as it's not fully implemented with the new init.
