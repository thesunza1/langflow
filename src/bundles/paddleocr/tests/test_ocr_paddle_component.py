"""Unit tests for the OCR Paddle extension bundle (``lfx-paddleocr``)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from lfx_paddleocr import OcrPaddleComponent


@pytest.fixture
def default_kwargs():
    return {
        "images": [],
        "paste_images": "",
        "lang": "Auto",
        "use_layout": True,
        "timeout": 300,
        "_session_id": "test-session",
    }


def test_component_initialization(default_kwargs):
    component = OcrPaddleComponent(**default_kwargs)

    frontend_node = component.to_frontend_node()
    node_data = frontend_node["data"]["node"]
    template = node_data["template"]

    assert template["images"]["type"] == "file"
    assert template["lang"]["value"] == "Auto"
    assert template["lang"]["options"] == [
        "Auto", "chinese", "english", "vietnamese", "japanese", "korean", "french", "german",
    ]
    assert template["use_layout"]["value"] is True
    assert template["timeout"]["value"] == 300


def test_component_display():
    assert OcrPaddleComponent.display_name == "OCR Paddle"
    assert OcrPaddleComponent.name == "OcrPaddle"
    assert OcrPaddleComponent.icon == "file-text"


def test_component_inputs_outputs(default_kwargs):
    component = OcrPaddleComponent(**default_kwargs)

    assert len(component.inputs) == 5
    assert len(component.outputs) == 2

    # Check inputs by name
    input_names = {inp.name for inp in component.inputs}
    assert "images" in input_names
    assert "paste_images" in input_names
    assert "lang" in input_names
    assert "use_layout" in input_names
    assert "timeout" in input_names

    # Check outputs
    output_names = {out.name for out in component.outputs}
    assert "markdown_output" in output_names
    assert "dataframe" in output_names


def test_get_images_config_files(default_kwargs):
    """Test _get_images_config with temporary image files."""
    import tempfile

    component = OcrPaddleComponent(**default_kwargs)

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(b"fake png data")
        f.flush()
        component.images = [f.name]

        config = component._get_images_config()

        assert len(config) == 1
        assert config[0]["kind"] == "file"
        assert config[0]["path"] == f.name
        assert config[0]["data"] is None
        assert config[0]["file_name"] == Path(f.name).name


def test_get_images_config_paste(default_kwargs):
    """Test _get_images_config with base64-encoded paste data."""
    import base64

    component = OcrPaddleComponent(**default_kwargs)
    b64_data = base64.b64encode(b"fake image").decode("utf-8")
    component.paste_images = b64_data

    config = component._get_images_config()

    assert len(config) == 1
    assert config[0]["kind"] == "base64"
    assert config[0]["path"] is None
    assert config[0]["data"] == b64_data
    assert "pasted_image" in config[0]["file_name"]


def test_get_images_config_both(default_kwargs):
    """Test _get_images_config with both files and paste data."""
    import base64
    import tempfile

    component = OcrPaddleComponent(**default_kwargs)

    # Add a file
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        f.write(b"fake jpg")
        f.flush()
        component.images = [f.name]

        # Add paste data
        b64_data = base64.b64encode(b"paste image").decode("utf-8")
        component.paste_images = b64_data

        config = component._get_images_config()

        assert len(config) == 2
        assert config[0]["kind"] == "file"
        assert config[1]["kind"] == "base64"


def test_get_images_config_no_images(default_kwargs):
    """Test _get_images_config with no images provided."""
    component = OcrPaddleComponent(**default_kwargs)
    config = component._get_images_config()
    assert len(config) == 0


def test_paddleocr_lang_map(default_kwargs):
    """Test the language mapping."""
    from lfx_paddleocr.components.paddleocr.ocr_paddle import PADDLEOCR_LANG_MAP

    assert PADDLEOCR_LANG_MAP["Auto"] == "ch"
    assert PADDLEOCR_LANG_MAP["vietnamese"] == "vi"
    assert PADDLEOCR_LANG_MAP["english"] == "en"
    assert PADDLEOCR_LANG_MAP["japanese"] == "japan"
    assert len(PADDLEOCR_LANG_MAP) == 8


@patch("subprocess.Popen")
def test_process_images_no_files(mock_popen, default_kwargs):
    """Test process_images with no images raises ValueError."""
    component = OcrPaddleComponent(**default_kwargs)
    with pytest.raises(ValueError, match="No images provided"):
        component.process_images()


@patch("subprocess.Popen")
def test_process_images_dataframe_no_files(mock_popen, default_kwargs):
    """Test process_images_dataframe with no images raises ValueError."""
    component = OcrPaddleComponent(**default_kwargs)
    with pytest.raises(ValueError, match="No images provided"):
        component.process_images_dataframe()
