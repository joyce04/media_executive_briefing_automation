"""WeasyPrint HTML-to-PDF generator."""
from pathlib import Path
import structlog

logger = structlog.get_logger()


def generate_pdf(html_content: str, output_path: str) -> bool:
    """Convert HTML to PDF using WeasyPrint. Returns True on success."""
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        font_config = FontConfiguration()
        css_path = Path(__file__).parent / "templates" / "css" / "pdf.css"
        css = CSS(filename=str(css_path), font_config=font_config) if css_path.exists() else None
        html = HTML(string=html_content, base_url=str(Path(__file__).parent / "templates"))
        if css:
            html.write_pdf(output_path, stylesheets=[css], font_config=font_config)
        else:
            html.write_pdf(output_path)
        logger.info("pdf_generated", path=output_path)
        return True
    except ImportError:
        logger.warning("weasyprint_not_installed", note="Install weasyprint for PDF generation")
        return False
    except Exception as e:
        logger.error("pdf_generation_failed", error=str(e))
        return False
