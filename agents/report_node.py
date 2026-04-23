"""Node 7: Render Jinja2 templates, generate PDF, and send email."""
import structlog
from reports.generator import build_report_context
from reports.pdf_generator import generate_pdf
from reports.email_sender import send_report_email
from database.repositories.report_repo import insert_report_record, update_report_delivery
from database.repositories.pipeline_repo import update_run_status
from config.settings import settings
from models.state import PipelineState
from pathlib import Path

logger = structlog.get_logger()


async def run(state: PipelineState) -> dict:
    run_uuid = state["run_uuid"]
    run_date = state["run_date"]
    org_id = state["org_id"]
    org_config = state["org_config"]
    org = org_config["org"]
    synthesis_id = state.get("synthesis_id")
    dry_run = state.get("_dry_run", False)

    logger.info("report_node_start", run_uuid=run_uuid, synthesis_id=synthesis_id,
                org=org["slug"], dry_run=dry_run)
    update_run_status(run_uuid, "reporting")

    if not synthesis_id:
        logger.warning("report_node_no_synthesis", run_uuid=run_uuid)
        return {
            "report_paths": {},
            "emails_sent": [],
            "stage": "report",
            "errors": ["report_node: no synthesis available"],
        }

    try:
        context = build_report_context(run_uuid=run_uuid, run_date=run_date,
                                       org_id=org_id, state=state)

        from jinja2 import Environment, FileSystemLoader
        template_dir = Path(__file__).parent.parent / "reports" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
        html_template = env.get_template("email_report.html.jinja2")
        html_content = html_template.render(**context)

        # Namespace output by org slug to avoid collisions
        output_dir = Path(settings.reports_output_dir) / org["slug"]
        output_dir.mkdir(parents=True, exist_ok=True)
        html_path = output_dir / f"{run_date}.html"
        html_path.write_text(html_content, encoding="utf-8")

        pdf_path = output_dir / f"{run_date}.pdf"
        pdf_template = env.get_template("pdf_report.html.jinja2")
        pdf_html = pdf_template.render(**context)
        generate_pdf(html_content=pdf_html, output_path=str(pdf_path))

        report_paths = {"html": str(html_path), "pdf": str(pdf_path)}

        insert_report_record(org_id=org_id, run_uuid=run_uuid, run_date=run_date,
                             report_format="html_email", file_path=str(html_path),
                             file_size_bytes=html_path.stat().st_size)
        insert_report_record(org_id=org_id, run_uuid=run_uuid, run_date=run_date,
                             report_format="pdf", file_path=str(pdf_path),
                             file_size_bytes=pdf_path.stat().st_size if pdf_path.exists() else None)

        emails_sent = []
        if dry_run:
            logger.info("report_node_dry_run_skip_email", html=str(html_path), pdf=str(pdf_path))
            print(f"\n[DRY RUN] Email delivery skipped. Reports saved to:\n"
                  f"  HTML: {html_path}\n  PDF:  {pdf_path}")
        else:
            recipients = org_config.get("recipients", {})
            to_emails = [r["email"] for r in recipients.get("to", [])]
            cc_emails = [r["email"] for r in recipients.get("cc", [])]
            bcc_emails = [r["email"] for r in recipients.get("bcc", [])]
            org_short = org.get("name_short", org["slug"].upper())
            subject = f"[{org_short}] {run_date} Daily Briefing"

            try:
                send_report_email(
                    to_emails=to_emails,
                    cc_emails=cc_emails,
                    bcc_emails=bcc_emails,
                    subject=subject,
                    html_content=html_content,
                    pdf_path=str(pdf_path) if pdf_path.exists() else None,
                    run_date=run_date,
                    org_short=org_short,
                    dry_run=False,
                )
                emails_sent = to_emails + cc_emails + bcc_emails
                logger.info("report_node_email_sent", recipients=emails_sent)
            except Exception as e:
                logger.error("report_node_email_failed", error=str(e))

        logger.info("report_node_done", html=str(html_path), pdf=str(pdf_path))
        return {"report_paths": report_paths, "emails_sent": emails_sent, "stage": "report"}

    except Exception as e:
        logger.error("report_node_failed", error=str(e))
        return {
            "report_paths": {},
            "emails_sent": [],
            "stage": "report",
            "errors": [f"report_node: {e}"],
        }
