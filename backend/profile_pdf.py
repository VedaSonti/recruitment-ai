"""Generate selectable-text, iSOFT-styled candidate profile PDFs."""

from html import escape
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

MAROON = colors.HexColor("#5C0D1B")
RED = colors.HexColor("#E01111")
CHARCOAL = colors.HexColor("#333333")
BLUSH = colors.HexColor("#F2E1E3")
MUTED = colors.HexColor("#667085")
WHITE = colors.white


def _clean(value: object) -> str:
    return str(value or "").strip()


def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_clean(text)).replace("\n", "<br/>"), style)


def _bullets(values: Iterable[object], style: ParagraphStyle) -> list[Paragraph]:
    return [
        Paragraph(f"- {escape(_clean(value))}", style)
        for value in values
        if _clean(value)
    ]


class CandidateProfileDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, candidate_name: str, professional_title: str):
        super().__init__(
            filename,
            pagesize=letter,
            leftMargin=0.48 * inch,
            rightMargin=0.48 * inch,
            topMargin=1.42 * inch,
            bottomMargin=0.52 * inch,
            title=f"Candidate Profile - {candidate_name}",
            author="Recruitment AI",
            subject="Client-ready candidate profile",
        )
        self.candidate_name = candidate_name
        self.professional_title = professional_title
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="profile_body",
            leftPadding=10,
            rightPadding=10,
            topPadding=10,
            bottomPadding=10,
        )
        self.addPageTemplates(
            [PageTemplate(id="profile", frames=[frame], onPage=self._draw_page)]
        )

    def _draw_page(self, canvas, _doc):
        width, height = letter
        canvas.saveState()
        canvas.setStrokeColor(MAROON)
        canvas.setLineWidth(3)
        canvas.rect(0.25 * inch, 0.22 * inch, width - 0.5 * inch, height - 0.44 * inch)

        canvas.setFillColor(MAROON)
        canvas.rect(0.38 * inch, height - 1.25 * inch, width - 0.76 * inch, 0.86 * inch, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 21 if canvas.getPageNumber() == 1 else 16)
        canvas.drawString(0.55 * inch, height - 0.78 * inch, self.candidate_name.upper()[:42])
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(0.56 * inch, height - 1.03 * inch, self.professional_title.upper()[:70])

        canvas.setFillColor(RED)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawRightString(width - 0.55 * inch, height - 0.74 * inch, "CANDIDATE PROFILE")

        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawCentredString(width / 2, 0.35 * inch, "Candidate Profile  |  Confidential  |  Recruiter Review Required")
        canvas.restoreState()


def generate_profile_pdf(profile: dict, output_path: Path) -> None:
    """Generate a branded PDF using only fields already stored in the uplift profile."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    name = _clean(profile.get("name")) or "Candidate"
    title = _clean(profile.get("professional_title")) or "Professional Profile"
    visibility = profile.get("section_visibility") or {}

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "ProfileHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=MAROON,
        spaceBefore=9,
        spaceAfter=6,
    )
    subheading = ParagraphStyle(
        "ProfileSubheading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=CHARCOAL,
        spaceBefore=6,
        spaceAfter=3,
    )
    body = ParagraphStyle(
        "ProfileBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.4,
        leading=13.2,
        textColor=CHARCOAL,
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "ProfileSmall",
        parent=body,
        fontSize=8.3,
        leading=11.2,
        textColor=MUTED,
    )
    label = ParagraphStyle(
        "ProfileLabel",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=8.3,
        leading=10,
        textColor=MAROON,
        spaceAfter=1,
    )
    side_heading = ParagraphStyle(
        "ProfileSideHeading",
        parent=subheading,
        fontSize=10,
        leading=12,
        textColor=WHITE,
        spaceBefore=10,
        spaceAfter=5,
    )
    side_body = ParagraphStyle(
        "ProfileSideBody",
        parent=body,
        fontSize=8.4,
        leading=11.2,
        textColor=WHITE,
        spaceAfter=3,
    )

    doc = CandidateProfileDocTemplate(str(output_path), name, title)
    story = []

    contact = profile.get("contact") or {}
    contact_values = [contact.get(key) for key in ("location", "phone", "email")]
    contact_values = [_clean(value) for value in contact_values if _clean(value)]
    if visibility.get("contact", True) and contact_values:
        contact_table = Table(
            [[_paragraph(value, small) for value in contact_values]],
            colWidths=[doc.width / len(contact_values)] * len(contact_values),
        )
        contact_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BLUSH),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D9B9BE")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.extend([contact_table, Spacer(1, 8)])

    sidebar = []
    skills = [
        *(profile.get("core_skills") or []),
        *(profile.get("technical_skills") or []),
    ]
    if visibility.get("skills", True) and any(_clean(skill) for skill in skills):
        sidebar.append(Paragraph("CORE & TECHNICAL SKILLS", side_heading))
        sidebar.extend(_bullets(skills, side_body))

    education = profile.get("education") or []
    if visibility.get("education", True) and education:
        sidebar.append(Paragraph("EDUCATION", side_heading))
        for item in education:
            sidebar.append(_paragraph(_clean(item.get("degree")), side_heading))
            detail = "<br/>".join(
                escape(value)
                for value in [_clean(item.get("institution")), _clean(item.get("year"))]
                if value
            )
            if detail:
                sidebar.append(Paragraph(detail, side_body))

    certifications = profile.get("certifications") or []
    if visibility.get("certifications", True) and certifications:
        sidebar.append(Paragraph("CERTIFICATIONS", side_heading))
        sidebar.extend(_bullets(certifications, side_body))

    additional = profile.get("additional_information") or {}
    if visibility.get("additional", True) and any(_clean(value) for value in additional.values()):
        sidebar.append(Paragraph("ADDITIONAL INFORMATION", side_heading))
        for key, label_text in (("work_rights", "Work rights"), ("notice_period", "Availability")):
            if _clean(additional.get(key)):
                sidebar.append(_paragraph(label_text, side_heading))
                sidebar.append(_paragraph(additional.get(key), side_body))

    main_column = [Paragraph("CANDIDATE PROFILE", ParagraphStyle(
        "ProfileKicker", parent=label, textColor=RED, fontSize=8.8, spaceAfter=2
    ))]
    if visibility.get("summary", True) and _clean(profile.get("professional_summary")):
        main_column.extend([
            Paragraph("Professional Summary", heading),
            _paragraph(profile.get("professional_summary"), body),
        ])

    experience = profile.get("professional_experience") or []
    if visibility.get("experience", True) and experience:
        main_column.append(Paragraph("Professional Experience", heading))
        for role in experience:
            role_line = " | ".join(
                value
                for value in [
                    _clean(role.get("title")),
                    _clean(role.get("company")),
                    " - ".join(
                        value
                        for value in [_clean(role.get("start_year")), _clean(role.get("end_year")) or ("Present" if role.get("is_current") else "")]
                        if value
                    ),
                ]
                if value
            )
            main_column.append(_paragraph(role_line, subheading))
            main_column.extend(_bullets(role.get("highlights") or [], body))

    achievements = profile.get("key_achievements") or []
    if visibility.get("achievements", True) and achievements:
        main_column.append(Paragraph("Key Projects & Achievements", heading))
        main_column.extend(_bullets(achievements, body))

    profile_table = Table(
        [[sidebar, main_column]],
        colWidths=[doc.width * 0.36, doc.width * 0.64],
        splitByRow=1,
        splitInRow=1,
    )
    profile_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), MAROON),
        ("BACKGROUND", (1, 0), (1, 0), WHITE),
        ("LINEBEFORE", (1, 0), (1, 0), 1.2, RED),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(profile_table)

    doc.build(story)
