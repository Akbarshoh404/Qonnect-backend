"""
Storage provider abstraction.
Defines the interface all storage providers must implement.
"""
from abc import ABC, abstractmethod
from typing import Optional, BinaryIO


class StorageProvider(ABC):
    """Abstract base class for file storage providers."""

    @abstractmethod
    def ensure_root_folder(self, user) -> str:
        """
        Ensure the root Qonnect folder exists for the user.
        Returns the folder ID (or path).
        """
        ...

    @abstractmethod
    def create_qr_folder(self, user, short_code: str) -> str:
        """
        Create a sub-folder for a specific QR code.
        Returns the folder ID (or path).
        """
        ...

    @abstractmethod
    def upload_file(
        self,
        user,
        folder_id: str,
        file_data: BinaryIO,
        filename: str,
        mime_type: str,
    ) -> dict:
        """
        Upload a file to storage.
        
        Returns dict with at minimum:
            {
                'file_id': str,
                'filename': str,
                'mime_type': str,
                'size': int,
            }
        """
        ...

    @abstractmethod
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
        """
        Replace an existing file with a new one.
        Optionally trash the old file.
        
        Returns same dict as upload_file.
        """
        ...

    @abstractmethod
    def delete_file(self, user, file_id: str, permanent: bool = False) -> bool:
        """
        Delete (or trash) a file.
        Returns True if successful.
        """
        ...

    @abstractmethod
    def get_download_url(self, user, file_id: str) -> str:
        """
        Get a URL that allows downloading the file.
        May be a direct link or a temporary signed URL.
        """
        ...

    @abstractmethod
    def get_file_metadata(self, user, file_id: str) -> Optional[dict]:
        """
        Get metadata for a file (name, size, mime_type).
        Returns None if the file doesn't exist.
        """
        ...

    @abstractmethod
    def is_connected(self, user) -> bool:
        """Check if the user's storage is connected and accessible."""
        ...
