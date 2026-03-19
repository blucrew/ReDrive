from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def get_jinja_env(template_dir=None):
    if template_dir is None:
        template_dir = Path(__file__).parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
