import unittest

from app.domain.image import (
    ImageFormat,
    ImageUpload,
    ImageValidationError,
    ImageValidator,
    ImageView,
    detect_image_format,
    sanitize_filename,
)

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"png" * 20
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"webp" * 20


class ImageValidatorTests(unittest.TestCase):
    def test_detects_supported_formats(self) -> None:
        self.assertEqual(detect_image_format(JPEG), ImageFormat.JPEG)
        self.assertEqual(detect_image_format(PNG), ImageFormat.PNG)
        self.assertEqual(detect_image_format(WEBP), ImageFormat.WEBP)
        self.assertIsNone(detect_image_format(b"not-an-image"))

    def test_valid_multiview_batch(self) -> None:
        uploads = (
            ImageUpload("front.jpg", "image/jpeg", JPEG, ImageView.FRONT),
            ImageUpload("left.png", "image/png", PNG, ImageView.LEFT),
            ImageUpload("back.webp", "image/webp", WEBP, ImageView.BACK),
        )
        validated = ImageValidator().validate(uploads)
        self.assertEqual(len(validated), 3)
        self.assertEqual(validated[0].content_type, "image/jpeg")
        self.assertEqual(validated[1].view, ImageView.LEFT)

    def test_rejects_unknown_format(self) -> None:
        with self.assertRaises(ImageValidationError) as context:
            ImageValidator().validate((ImageUpload("x.txt", "text/plain", b"hello"),))
        self.assertEqual(context.exception.code, "INVALID_IMAGE_TYPE")

    def test_rejects_content_type_mismatch(self) -> None:
        with self.assertRaises(ImageValidationError) as context:
            ImageValidator().validate((ImageUpload("x.png", "image/jpeg", PNG),))
        self.assertEqual(context.exception.code, "INVALID_IMAGE_TYPE")

    def test_rejects_too_many_images(self) -> None:
        uploads = tuple(
            ImageUpload(f"{index}.jpg", "image/jpeg", JPEG + bytes([index]))
            for index in range(3)
        )
        with self.assertRaises(ImageValidationError) as context:
            ImageValidator(max_images=2).validate(uploads)
        self.assertEqual(context.exception.code, "TOO_MANY_IMAGES")

    def test_rejects_oversized_image(self) -> None:
        with self.assertRaises(ImageValidationError) as context:
            ImageValidator(max_image_bytes=10).validate(
                (ImageUpload("big.jpg", "image/jpeg", JPEG),)
            )
        self.assertEqual(context.exception.code, "IMAGE_TOO_LARGE")

    def test_rejects_duplicate_image(self) -> None:
        with self.assertRaises(ImageValidationError) as context:
            ImageValidator().validate(
                (
                    ImageUpload("a.jpg", "image/jpeg", JPEG),
                    ImageUpload("b.jpg", "image/jpeg", JPEG),
                )
            )
        self.assertEqual(context.exception.code, "DUPLICATE_IMAGE")

    def test_sanitizes_filename_and_adds_extension(self) -> None:
        self.assertEqual(sanitize_filename("../../front", ImageFormat.JPEG), "front.jpg")
        self.assertEqual(sanitize_filename("左视图.png", ImageFormat.PNG), "左视图.png")


if __name__ == "__main__":
    unittest.main()
