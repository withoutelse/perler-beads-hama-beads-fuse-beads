from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import PurePath


class ImageFormat(str, Enum):
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"


class ImageView(str, Enum):
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    UNKNOWN = "unknown"


class ImageValidationError(ValueError):
    def __init__(self, code: str, message: str, *, filename: str | None = None) -> None:
        self.code = code
        self.filename = filename
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ImageUpload:
    filename: str
    content_type: str | None
    data: bytes
    view: ImageView = ImageView.UNKNOWN


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    view: ImageView
    data: bytes


@dataclass(frozen=True, slots=True)
class StoredImage:
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    view: ImageView
    relative_path: str


def detect_image_format(data: bytes) -> ImageFormat | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ImageFormat.JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ImageFormat.PNG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ImageFormat.WEBP
    return None


def sanitize_filename(filename: str, image_format: ImageFormat) -> str:
    name = PurePath(filename or "image").name
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._") or "image"
    if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        extension = {
            ImageFormat.JPEG: ".jpg",
            ImageFormat.PNG: ".png",
            ImageFormat.WEBP: ".webp",
        }[image_format]
        name = f"{name}{extension}"
    return name


class ImageValidator:
    def __init__(
        self,
        *,
        max_images: int = 12,
        max_image_bytes: int = 20 * 1024 * 1024,
        max_total_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        if max_images <= 0:
            raise ValueError("max_images must be positive")
        if max_image_bytes <= 0 or max_total_bytes <= 0:
            raise ValueError("image size limits must be positive")
        self.max_images = max_images
        self.max_image_bytes = max_image_bytes
        self.max_total_bytes = max_total_bytes

    def validate(self, uploads: Sequence[ImageUpload]) -> tuple[ValidatedImage, ...]:
        if not uploads:
            raise ImageValidationError("NO_IMAGES", "至少上传 1 张图片")
        if len(uploads) > self.max_images:
            raise ImageValidationError(
                "TOO_MANY_IMAGES",
                f"单个项目最多上传 {self.max_images} 张多视角图片",
            )

        total_bytes = 0
        seen_hashes: set[str] = set()
        validated: list[ValidatedImage] = []
        for upload in uploads:
            filename = upload.filename or "image"
            if not upload.data:
                raise ImageValidationError("EMPTY_IMAGE", "图片内容为空", filename=filename)
            if len(upload.data) > self.max_image_bytes:
                raise ImageValidationError(
                    "IMAGE_TOO_LARGE",
                    f"单张图片不能超过 {self.max_image_bytes // (1024 * 1024)} MB",
                    filename=filename,
                )
            total_bytes += len(upload.data)
            if total_bytes > self.max_total_bytes:
                raise ImageValidationError(
                    "TOTAL_IMAGES_TOO_LARGE",
                    f"项目图片总大小不能超过 {self.max_total_bytes // (1024 * 1024)} MB",
                    filename=filename,
                )

            image_format = detect_image_format(upload.data)
            if image_format is None:
                raise ImageValidationError(
                    "INVALID_IMAGE_TYPE",
                    "只支持 JPG、PNG、WebP",
                    filename=filename,
                )
            if upload.content_type and upload.content_type not in {
                image_format.value,
                "image/jpg",
            }:
                raise ImageValidationError(
                    "INVALID_IMAGE_TYPE",
                    f"文件扩展名与内容不一致：{upload.content_type}",
                    filename=filename,
                )

            digest = sha256(upload.data).hexdigest()
            if digest in seen_hashes:
                raise ImageValidationError(
                    "DUPLICATE_IMAGE",
                    "检测到重复图片，请移除重复视角",
                    filename=filename,
                )
            seen_hashes.add(digest)
            validated.append(
                ValidatedImage(
                    filename=sanitize_filename(filename, image_format),
                    content_type=image_format.value,
                    size_bytes=len(upload.data),
                    sha256=digest,
                    view=upload.view,
                    data=upload.data,
                )
            )
        return tuple(validated)
