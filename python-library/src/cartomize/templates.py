"""Access to the 24 original Cartomize layout templates."""
from pathlib import Path
from ._core.template_catalog import TemplateCatalog
from ._core.layout_plan import build_layout_plan


def catalog():
    return TemplateCatalog(Path(__file__).parent / "templates_library")


def list_templates(category="", search=""):
    return [{"id": s.template_id, "name": s.name, "category": s.category,
             "page_format": s.page_format, "map_frames": s.map_count}
            for s in catalog().search(search, category)]


def get_template(template_id):
    return catalog().get(template_id)


def layout_plan(template_id):
    return build_layout_plan(get_template(template_id))
