from order_ocr.app import OrderRecognizerApp


def test_exception_message_is_bound_before_deferred_callback():
    callbacks = []

    def after(delay, callback):
        callbacks.append(callback)

    try:
        raise RuntimeError("boom")
    except Exception as exc:
        message = f"OCR failed: {exc}"
        after(0, lambda message=message: message)

    assert callbacks[0]() == "OCR failed: boom"
