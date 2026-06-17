"""Unit tests for the VL Images extension bundle (``lfx-vlimages``)."""

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
from lfx_vlimages import VLImagesComponent
from lfx.schema import Message, DataFrame


@pytest.fixture
def default_kwargs():
    return {
        "images": [],
        "paste_images": "",
        "model_name": "unsloth/Qwen3.5-2B-MTP-GGUF",
        "api_base": "http://localhost:8000/v1",
        "api_key": "",
        "temperature": 0.1,
        "max_tokens": 2000,
        "max_model_len": 50000,
        "no_think_mode": True,
        "system_prompt": "Test prompt",
        "_session_id": "test-session",
    }


def test_component_initialization(default_kwargs):
    component = VLImagesComponent(**default_kwargs)

    frontend_node = component.to_frontend_node()
    node_data = frontend_node["data"]["node"]
    template = node_data["template"]

    assert template["images"]["type"] == "file"
    assert template["model_name"]["value"] == "unsloth/Qwen3.5-2B-MTP-GGUF"
    assert template["api_base"]["value"] == "http://localhost:8000/v1"
    assert template["max_tokens"]["value"] == 2000
    assert template["max_model_len"]["value"] == 50000
    assert template["no_think_mode"]["value"] is True
    assert template["temperature"]["value"] == 0.1


def test_component_display():
    assert VLImagesComponent.display_name == "VL Images"
    assert VLImagesComponent.name == "VLImages"
    assert VLImagesComponent.icon == "image"


def test_component_inputs_outputs(default_kwargs):
    component = VLImagesComponent(**default_kwargs)

    assert len(component.inputs) == 10
    assert len(component.outputs) == 2

    # Check inputs by name
    input_names = {inp.name for inp in component.inputs}
    assert "images" in input_names
    assert "paste_images" in input_names
    assert "model_name" in input_names
    assert "api_base" in input_names
    assert "api_key" in input_names
    assert "temperature" in input_names
    assert "max_tokens" in input_names
    assert "max_model_len" in input_names
    assert "no_think_mode" in input_names
    assert "system_prompt" in input_names

    # Check outputs
    output_names = {out.name for out in component.outputs}
    assert "markdown_output" in output_names
    assert "dataframe" in output_names


def test_collect_images_files(default_kwargs):
    """Test _collect_images with temporary image files."""
    import tempfile

    component = VLImagesComponent(**default_kwargs)

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(b"fake png data")
        f.flush()
        component.images = [f.name]

        images = component._collect_images()

        assert len(images) == 1
        name, data = images[0]
        assert name == Path(f.name).name
        assert data == b"fake png data"


def test_collect_images_paste(default_kwargs):
    """Test _collect_images with base64-encoded paste data."""
    component = VLImagesComponent(**default_kwargs)
    b64_data = base64.b64encode(b"paste image data").decode("utf-8")
    component.paste_images = b64_data

    images = component._collect_images()

    assert len(images) == 1
    name, data = images[0]
    assert "pasted_image" in name
    assert data == b"paste image data"


def test_collect_images_both(default_kwargs):
    """Test _collect_images with both files and paste."""
    import tempfile

    component = VLImagesComponent(**default_kwargs)

    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        f.write(b"jpg data")
        f.flush()
        component.images = [f.name]

        b64_data = base64.b64encode(b"paste data").decode("utf-8")
        component.paste_images = b64_data

        images = component._collect_images()

        assert len(images) == 2


def test_collect_images_no_images(default_kwargs):
    """Test _collect_images raises ValueError when no images."""
    component = VLImagesComponent(**default_kwargs)
    with pytest.raises(ValueError, match="No images provided"):
        component._collect_images()


def test_image_to_base64_url(default_kwargs):
    """Test _image_to_base64_url generates a valid data URL."""
    component = VLImagesComponent(**default_kwargs)
    url = component._image_to_base64_url(b"\x89PNG\r\n\x1a\n", "test.png")
    assert url.startswith("data:image/png;base64,")

    url_jpg = component._image_to_base64_url(b"\xff\xd8\xff\xe0", "photo.jpg")
    assert url_jpg.startswith("data:image/jpeg;base64,")

    url_webp = component._image_to_base64_url(b"RIFF\x00\x00\x00\x00WEBPVP8", "img.webp")
    assert url_webp.startswith("data:image/webp;base64,")


def test_build_system_prompt_no_think(default_kwargs):
    """Test that no_think_mode adds the thinking instruction."""
    component = VLImagesComponent(**default_kwargs)
    component.no_think_mode = True
    component.system_prompt = "Describe the image."

    prompt = component._build_system_prompt()

    assert "Describe the image" in prompt
    assert "Do NOT output any thinking" in prompt


def test_build_system_prompt_allow_think(default_kwargs):
    """Test that no_think_mode=False does not add the thinking instruction."""
    component = VLImagesComponent(**default_kwargs)
    component.no_think_mode = False
    component.system_prompt = "Describe the image."

    prompt = component._build_system_prompt()

    assert "Describe the image" in prompt
    assert "Do NOT output any thinking" not in prompt


@patch("openai.OpenAI")
def test_call_vlm_success(mock_openai, default_kwargs):
    """Test _call_vlm returns the description from the API."""
    # Set up mock
    mock_client = mock_openai.return_value
    mock_response = mock_client.chat.completions.create.return_value
    mock_response.choices = [
        type(
            "obj",
            (),
            {"message": type("obj", (), {"content": "## Test\n\nThis is a test description."})()},
        )()
    ]

    component = VLImagesComponent(**default_kwargs)
    result = component._call_vlm("test.png", b"fake image bytes")

    assert "Test" in result
    assert "test description" in result.lower()


@patch("openai.OpenAI")
def test_call_vlm_connection_error(mock_openai, default_kwargs):
    """Test _call_vlm raises ConnectionError when vLLM is unreachable."""
    from openai import APIError

    mock_client = mock_openai.return_value
    mock_client.chat.completions.create.side_effect = APIError(
        "Connection refused",
        request=None,
        body={"message": "Connection refused"},
    )

    component = VLImagesComponent(**default_kwargs)
    component.api_base = "http://localhost:9999/v1"

    with pytest.raises(ConnectionError, match="connect|refused"):
        component._call_vlm("test.png", b"fake image bytes")


@patch.object(VLImagesComponent, "_call_vlm")
def test_describe_images(mock_call_vlm, default_kwargs):
    """Test describe_images returns combined Markdown."""
    import tempfile

    mock_call_vlm.return_value = "## photo.png\n\nA beautiful sunset."

    component = VLImagesComponent(**default_kwargs)

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(b"fake png")
        f.flush()
        component.images = [f.name]

        result = component.describe_images()

        assert isinstance(result, Message)
        assert "photo.png" in result.text
        assert "beautiful sunset" in result.text


@patch.object(VLImagesComponent, "_call_vlm")
def test_describe_images_dataframe(mock_call_vlm, default_kwargs):
    """Test describe_images_dataframe returns DataFrame."""
    import tempfile

    mock_call_vlm.return_value = "A sunset."

    component = VLImagesComponent(**default_kwargs)

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(b"fake png")
        f.flush()
        component.images = [f.name]

        result = component.describe_images_dataframe()

        assert isinstance(result, DataFrame)
        assert len(result) == 1
        assert "file" in result.columns
        assert "description" in result.columns
        assert result["file"].iloc[0] is not None
        assert result["description"].iloc[0] == "A sunset."
