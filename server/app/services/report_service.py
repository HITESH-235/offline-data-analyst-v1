import os
import uuid
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from fpdf import FPDF
from app.services.project_service import ProjectService
from app.utils.workspace import get_project_dir

logger = logging.getLogger(__name__)

class PDFReport(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, "Offline AI Data Analyst - Executive Report", border=0, align="R")
        self.ln(12)
        
    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        # Page number
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

class ReportService:
    @staticmethod
    def generate_report(
        db: Session,
        project_id: str,
        title: str,
        content_markdown: str
    ) -> Dict[str, str]:
        """
        Generates and saves a Markdown and PDF executive report.
        Returns the filenames and file paths.
        """
        project = ProjectService.get_project(db, project_id)
        if not project:
            raise ValueError("Project not found.")
            
        project_dir = get_project_dir(project.name)
        reports_dir = os.path.join(project_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        file_uuid = uuid.uuid4().hex[:8]
        safe_title = "".join([c if c.isalnum() or c in "-_" else "_" for c in title.lower()]).strip("_")
        
        md_filename = f"report_{safe_title}_{file_uuid}.md"
        pdf_filename = f"report_{safe_title}_{file_uuid}.pdf"
        
        md_path = os.path.join(reports_dir, md_filename)
        pdf_path = os.path.join(reports_dir, pdf_filename)
        
        # 1. Save Markdown File
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write(content_markdown)
            logger.info(f"Markdown report generated at: {md_path}")
        except Exception as e:
            logger.error(f"Failed to write Markdown report: {e}")
            raise IOError(f"Could not save Markdown report: {e}")
            
        # 2. Save PDF File using FPDF2
        try:
            pdf = PDFReport()
            pdf.add_page()
            
            # Title Page/Heading
            pdf.set_font("helvetica", "B", 18)
            pdf.set_text_color(40, 40, 40)
            pdf.cell(0, 10, title, ln=True, align="L")
            pdf.ln(5)
            
            # Separation Line
            pdf.set_draw_color(180, 180, 180)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(8)
            
            # Add Content Paragraphs
            pdf.set_font("helvetica", "", 10.5)
            pdf.set_text_color(50, 50, 50)
            
            lines = content_markdown.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    pdf.ln(3)
                    continue
                    
                # Handle basic Markdown styling structures
                if line.startswith("# "):
                    pdf.ln(4)
                    pdf.set_font("helvetica", "B", 14)
                    pdf.cell(0, 8, line[2:], ln=True)
                    pdf.set_font("helvetica", "", 10.5)
                    pdf.ln(2)
                elif line.startswith("## "):
                    pdf.ln(3)
                    pdf.set_font("helvetica", "B", 12.5)
                    pdf.cell(0, 7, line[3:], ln=True)
                    pdf.set_font("helvetica", "", 10.5)
                    pdf.ln(2)
                elif line.startswith("### "):
                    pdf.ln(2)
                    pdf.set_font("helvetica", "B", 11)
                    pdf.cell(0, 6, line[4:], ln=True)
                    pdf.set_font("helvetica", "", 10.5)
                    pdf.ln(1)
                elif line.startswith("- ") or line.startswith("* "):
                    # List bullet point
                    pdf.set_x(15)
                    pdf.cell(5, 5, chr(149), ln=False)  # Bullet char
                    pdf.multi_cell(0, 5, line[2:])
                else:
                    # Standard paragraph block text
                    pdf.multi_cell(0, 5, line)
                    
            pdf.output(pdf_path)
            logger.info(f"PDF report generated at: {pdf_path}")
            
        except Exception as e:
            logger.error(f"Failed to write PDF report: {e}")
            # Do not fail overall report generation if only PDF fails, but log it
            pdf_path = None
            pdf_filename = None
            
        return {
            "markdown_path": md_path,
            "markdown_filename": md_filename,
            "pdf_path": pdf_path,
            "pdf_filename": pdf_filename
        }
