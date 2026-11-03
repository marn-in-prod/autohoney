"""Configuration path tests."""

from datetime import datetime

from pipeline.config import generate_generation_id, generation_output_dir


def test_generation_output_dir_uses_generations_root(tmp_path):
    generations_dir = tmp_path / "generations"

    output_dir = generation_output_dir("demo-20260507-001", generations_dir)

    assert output_dir == generations_dir / "demo-20260507-001"
    assert output_dir.exists()


def test_generate_generation_id_increments_from_generations_dir(tmp_path):
    generations_dir = tmp_path / "generations"
    today = datetime.now().strftime("%Y%m%d")
    (generations_dir / f"demo-{today}-001").mkdir(parents=True)
    (generations_dir / f"demo-{today}-002").mkdir()

    generation_id = generate_generation_id("demo", generations_dir)

    assert generation_id.startswith("demo-")
    assert generation_id.endswith("-003")
