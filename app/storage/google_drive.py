"""
Google Drive storage provider.
Each user stores files in their own Google Drive under a Qonnect/ folder.
Uses the drive.file scope - only accesses files created by this app.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, BinaryIO

from flask import current_app
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from .base import StorageProvider
from app.utils.crypto import encrypt_json, decrypt_json

logger = logging.getLogger(__name__)

QONNECT_FOLDER_NAME = "Qonnect"
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "openid",
    "email",
    "profile",
]


class GoogleDriveStorageProvider(StorageProvider):
    """
    Stores user files in their own Google Drive.
    
    Drive scope used: drive.file
    - Can only read/write files created by this app
    - Cannot access other Drive files
    - Users see exactly what's stored under Qonnect/
    """

    def _get_credentials(self, user) -> Optional[Credentials]:
        """Get valid Google credentials for the user, refreshing if needed."""
        if not user.google_tokens_encrypted:
            return None

        encryption_key = current_app.config.get("ENCRYPTION_KEY", "")
        token_data = decrypt_json(user.google_tokens_encrypted, encryption_key)

        if not token_data:
            return None

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token and not refresh_token:
            return None

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=current_app.config["GOOGLE_CLIENT_ID"],
            client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
            scopes=DRIVE_SCOPES,
        )

        # Parse expiry — always store as offset-naive UTC internally
        expiry_str = token_data.get("token_expiry")
        if expiry_str:
            try:
                expiry_dt = datetime.fromisoformat(expiry_str)
                # Strip timezone info if present (google-auth uses offset-naive UTC)
                if expiry_dt.tzinfo is not None:
                    expiry_dt = expiry_dt.replace(tzinfo=None)
                creds.expiry = expiry_dt
            except Exception:
                pass  # If we can't parse expiry, let google-auth handle it

        # If expired (or no valid expiry), try to refresh using refresh_token
        if refresh_token and (not creds.token or creds.expired):
            try:
                creds.refresh(Request())
                self._save_credentials(user, creds)
                logger.debug(f"Refreshed token for user {user.id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for user {user.id}: {e}")
                return None

        return creds

    def _save_credentials(self, user, creds: Credentials) -> None:
        """Persist refreshed credentials back to the database."""
        from app.extensions import db

        encryption_key = current_app.config.get("ENCRYPTION_KEY", "")
        token_data = {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
            "scopes": list(creds.scopes) if creds.scopes else DRIVE_SCOPES,
        }
        user.google_tokens_encrypted = encrypt_json(token_data, encryption_key)
        db.session.commit()

    def _get_drive_service(self, user):
        """Build and return an authenticated Google Drive API service."""
        creds = self._get_credentials(user)
        if not creds:
            raise PermissionError("Google Drive not connected or credentials expired.")
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def is_connected(self, user) -> bool:
        """Check if the user has connected Google Drive."""
        try:
            creds = self._get_credentials(user)
            return creds is not None
        except Exception:
            return False

    def ensure_root_folder(self, user) -> str:
        """
        Ensure a 'Qonnect' folder exists in the user's Drive.
        Stores the folder ID on the user model for future use.
        Returns the folder ID.
        """
        from app.extensions import db

        # Return cached folder ID if we have a real one (not the "pending" placeholder)
        if user.drive_folder_id and user.drive_folder_id not in ("pending", ""):
            return user.drive_folder_id

        service = self._get_drive_service(user)

        # Check if Qonnect folder already exists (created by this app)
        results = service.files().list(
            q=f"name='{QONNECT_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive",
            fields="files(id, name)",
        ).execute()

        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
        else:
            # Create the Qonnect folder
            metadata = {
                "name": QONNECT_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            }
            folder = service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]
            logger.info(f"Created Qonnect folder for user {user.id}: {folder_id}")

        user.drive_folder_id = folder_id
        db.session.commit()
        return folder_id

    def create_qr_folder(self, user, short_code: str) -> str:
        """Create a sub-folder for a QR code within the Qonnect folder."""
        root_folder_id = self.ensure_root_folder(user)
        service = self._get_drive_service(user)

        folder_name = f"QR-{short_code}"

        # Check if sub-folder already exists
        results = service.files().list(
            q=(
                f"name='{folder_name}' "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and '{root_folder_id}' in parents "
                f"and trashed=false"
            ),
            spaces="drive",
            fields="files(id)",
        ).execute()

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_folder_id],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        return folder["id"]

    def upload_file(
        self,
        user,
        folder_id: str,
        file_data: BinaryIO,
        filename: str,
        mime_type: str,
    ) -> dict:
        """Upload a file to a specific Drive folder."""
        service = self._get_drive_service(user)

        file_metadata = {
            "name": filename,
            "parents": [folder_id],
        }

        media = MediaIoBaseUpload(file_data, mimetype=mime_type, resumable=True)

        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, mimeType, size",
        ).execute()

        logger.info(f"Uploaded file {filename} for user {user.id}: {uploaded.get('id')}")

        return {
            "file_id": uploaded["id"],
            "filename": uploaded.get("name", filename),
            "mime_type": uploaded.get("mimeType", mime_type),
            "size": int(uploaded.get("size", 0)),
        }

    def replace_file(
        self,
        user,
        old_file_id: str,
        folder_id: str,
        file_data: BinaryIO,
        filename: str,
        mime_type: str,
        trash_old: bool = True,
    ) -> dict:
        """Upload a new file and optionally trash the old one."""
        # Upload new file first
        new_file = self.upload_file(user, folder_id, file_data, filename, mime_type)

        # Trash old file if requested
        if old_file_id and trash_old:
            try:
                self.delete_file(user, old_file_id, permanent=False)
            except Exception as e:
                logger.warning(f"Failed to trash old file {old_file_id}: {e}")
                # Don't fail the replace operation if trash fails

        return new_file

    def delete_file(self, user, file_id: str, permanent: bool = False) -> bool:
        """Move file to trash (or permanently delete)."""
        service = self._get_drive_service(user)
        try:
            if permanent:
                service.files().delete(fileId=file_id).execute()
            else:
                service.files().update(
                    fileId=file_id, body={"trashed": True}
                ).execute()
            logger.info(f"{'Deleted' if permanent else 'Trashed'} file {file_id} for user {user.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_id}: {e}")
            return False

    def get_download_url(self, user, file_id: str) -> str:
        """
        Return a direct download URL for a Drive file.
        
        For drive.file scope, we use the webContentLink which requires auth,
        so we proxy through our backend instead of giving a direct Drive URL.
        This also hides the Drive file_id from end users.
        """
        # We route through backend /api/qr/:id/download
        # The actual Drive download happens server-side
        # This method is used internally to get the Drive URL for proxying
        service = self._get_drive_service(user)
        file_info = service.files().get(
            fileId=file_id,
            fields="id, webContentLink, webViewLink",
        ).execute()
        
        return file_info.get("webContentLink") or file_info.get("webViewLink", "")

    def get_file_content(self, user, file_id: str) -> Optional[bytes]:
        """Download and return file content as bytes."""
        from googleapiclient.http import MediaIoBaseDownload
        import io

        service = self._get_drive_service(user)
        try:
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buffer.seek(0)
            return buffer.read()
        except Exception as e:
            logger.error(f"Failed to download file {file_id}: {e}")
            return None

    def get_file_metadata(self, user, file_id: str) -> Optional[dict]:
        """Get metadata for a file."""
        service = self._get_drive_service(user)
        try:
            info = service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size, trashed",
            ).execute()
            if info.get("trashed"):
                return None
            return {
                "file_id": info["id"],
                "filename": info.get("name"),
                "mime_type": info.get("mimeType"),
                "size": int(info.get("size", 0)),
            }
        except Exception:
            return None

    @staticmethod
    def store_tokens(user, token_data: dict) -> None:
        """Store Google OAuth tokens for a user (encrypted)."""
        from app.extensions import db
        from flask import current_app

        encryption_key = current_app.config.get("ENCRYPTION_KEY", "")
        user.google_tokens_encrypted = encrypt_json(token_data, encryption_key)
        db.session.commit()


# Singleton provider instance
google_drive_provider = GoogleDriveStorageProvider()
