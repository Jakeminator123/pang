#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_beautiful_pdf.py - Generera snygg PDF från audit-data

Använder WeasyPrint för HTML/CSS-baserad PDF-generering (mycket snyggare än reportlab).
Försöker först WeasyPrint, faller tillbaka på reportlab om det saknas.

Användning:
    python generate_beautiful_pdf.py audit_report.json output.pdf
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional


def generate_with_weasyprint(audit_data: Dict[str, Any], output_path: Path) -> bool:
    """Generera PDF med WeasyPrint (HTML/CSS -> PDF, mycket snyggare)."""
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:
        return False

    try:
        company = audit_data.get("company", {})
        scores = audit_data.get("scores", {})
        strengths = audit_data.get("strengths", [])
        weaknesses = audit_data.get("weaknesses", [])
        recommendations = audit_data.get("recommendations", [])
        meta = audit_data.get("_meta", {})

        company_name = company.get("name", "Webbplats")
        url = meta.get("url", "")
        date = meta.get("audit_date", "")[:10] if meta.get("audit_date") else ""

        # HTML template med modern design
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page {{
            size: A4;
            margin: 2cm;
            @top-center {{
                content: "Webbplats-Audit Rapport";
                font-size: 10pt;
                color: #64748b;
            }}
            @bottom-center {{
                content: "Sida " counter(page) " av " counter(pages);
                font-size: 9pt;
                color: #94a3b8;
            }}
        }}
        
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #1e293b;
            background: #ffffff;
        }}
        
        .header {{
            background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
            color: white;
            padding: 2.5cm 0 1.5cm 0;
            margin: -2cm -2cm 2cm -2cm;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        
        .header h1 {{
            margin: 0;
            font-size: 32pt;
            font-weight: 700;
            letter-spacing: -0.5pt;
        }}
        
        .header .subtitle {{
            margin-top: 0.5cm;
            font-size: 14pt;
            opacity: 0.95;
        }}
        
        .meta {{
            background: #f8fafc;
            border-left: 4px solid #3b82f6;
            padding: 1cm;
            margin: 1.5cm 0;
            border-radius: 4px;
        }}
        
        .meta-item {{
            margin: 0.3cm 0;
            font-size: 11pt;
        }}
        
        .meta-label {{
            font-weight: 600;
            color: #475569;
            display: inline-block;
            width: 100px;
        }}
        
        h2 {{
            color: #1e40af;
            font-size: 18pt;
            margin-top: 1.5cm;
            margin-bottom: 0.8cm;
            padding-bottom: 0.3cm;
            border-bottom: 2px solid #e2e8f0;
            font-weight: 600;
        }}
        
        .description {{
            background: #f1f5f9;
            padding: 1cm;
            border-radius: 6px;
            margin: 1cm 0;
            font-size: 11pt;
            line-height: 1.7;
        }}
        
        .scores-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.8cm;
            margin: 1cm 0;
        }}
        
        .score-card {{
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 1cm;
            text-align: center;
            transition: transform 0.2s;
        }}
        
        .score-card .label {{
            font-size: 10pt;
            color: #64748b;
            margin-bottom: 0.5cm;
            font-weight: 500;
        }}
        
        .score-card .value {{
            font-size: 36pt;
            font-weight: 700;
            color: #1e40af;
            line-height: 1;
        }}
        
        .score-card.overall {{
            grid-column: 1 / -1;
            background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
            color: white;
            border: none;
        }}
        
        .score-card.overall .label {{
            color: rgba(255,255,255,0.9);
        }}
        
        .score-card.overall .value {{
            color: white;
        }}
        
        ul {{
            list-style: none;
            padding: 0;
            margin: 1cm 0;
        }}
        
        ul li {{
            background: #f8fafc;
            padding: 0.8cm;
            margin: 0.5cm 0;
            border-left: 4px solid #3b82f6;
            border-radius: 4px;
            font-size: 11pt;
            line-height: 1.6;
        }}
        
        ul.strengths li {{
            border-left-color: #10b981;
        }}
        
        ul.weaknesses li {{
            border-left-color: #f59e0b;
        }}
        
        ul.recommendations li {{
            border-left-color: #3b82f6;
        }}
        
        .footer {{
            margin-top: 2cm;
            padding-top: 1cm;
            border-top: 1px solid #e2e8f0;
            text-align: center;
            color: #94a3b8;
            font-size: 9pt;
        }}
        
        @media print {{
            .header {{
                page-break-after: avoid;
            }}
            h2 {{
                page-break-after: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Webbplats-Audit</h1>
        <div class="subtitle">{company_name}</div>
    </div>
    
    <div class="meta">
        <div class="meta-item">
            <span class="meta-label">URL:</span>
            <span>{url}</span>
        </div>
        <div class="meta-item">
            <span class="meta-label">Datum:</span>
            <span>{date}</span>
        </div>
    </div>
"""

        # Företagsbeskrivning
        desc = company.get("description", "")
        if desc:
            html_content += f"""
    <h2>Om företaget</h2>
    <div class="description">{desc}</div>
"""

        # Poäng
        if scores:
            html_content += """
    <h2>Bedömning</h2>
    <div class="scores-grid">
"""
            score_items = [
                ("Design", scores.get("design", "-")),
                ("Innehåll", scores.get("content", "-")),
                ("Användbarhet", scores.get("usability", "-")),
                ("Mobilvänlighet", scores.get("mobile", "-")),
                ("SEO", scores.get("seo", "-")),
            ]
            
            for label, value in score_items:
                if value != "-":
                    html_content += f"""
        <div class="score-card">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
        </div>
"""
            
            overall = scores.get("overall", "-")
            if overall != "-":
                html_content += f"""
        <div class="score-card overall">
            <div class="label">Helhetsomdöme</div>
            <div class="value">{overall}</div>
        </div>
"""
            html_content += """
    </div>
"""

        # Styrkor
        if strengths:
            html_content += """
    <h2>Styrkor</h2>
    <ul class="strengths">
"""
            for s in strengths:
                html_content += f"        <li>{s}</li>\n"
            html_content += "    </ul>\n"

        # Svagheter
        if weaknesses:
            html_content += """
    <h2>Förbättringsområden</h2>
    <ul class="weaknesses">
"""
            for w in weaknesses:
                html_content += f"        <li>{w}</li>\n"
            html_content += "    </ul>\n"

        # Rekommendationer
        if recommendations:
            html_content += """
    <h2>Rekommendationer</h2>
    <ul class="recommendations">
"""
            for r in recommendations:
                html_content += f"        <li>{r}</li>\n"
            html_content += "    </ul>\n"

        html_content += """
    <div class="footer">
        Rapport genererad av SajtStudio.se
    </div>
</body>
</html>
"""

        # Generera PDF
        font_config = FontConfiguration()
        HTML(string=html_content).write_pdf(
            output_path,
            stylesheets=[CSS(string="""
                @font-face {
                    font-family: 'Segoe UI';
                    src: local('Segoe UI');
                }
            """)],
            font_config=font_config
        )
        
        return True
        
    except Exception as e:
        print(f"⚠️  WeasyPrint-fel: {e}")
        return False


def generate_with_reportlab(audit_data: Dict[str, Any], output_path: Path) -> bool:
    """Fallback: Generera PDF med reportlab (enklare men fungerar alltid)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        return False

    try:
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=20,
            spaceAfter=12,
            textColor=colors.HexColor("#1e40af"),
        )
        heading_style = ParagraphStyle(
            "Heading",
            parent=styles["Heading2"],
            fontSize=14,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor("#1e40af"),
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=body_style,
            leftIndent=20,
            bulletIndent=10,
        )

        story = []
        company = audit_data.get("company", {})
        scores = audit_data.get("scores", {})
        strengths = audit_data.get("strengths", [])
        weaknesses = audit_data.get("weaknesses", [])
        recommendations = audit_data.get("recommendations", [])
        meta = audit_data.get("_meta", {})

        # Titel
        company_name = company.get("name", "Webbplats")
        story.append(Paragraph(f"Webbplats-Audit: {company_name}", title_style))
        story.append(Spacer(1, 0.3 * cm))

        # Meta-info
        url = meta.get("url", "")
        date = meta.get("audit_date", "")[:10] if meta.get("audit_date") else ""
        if url or date:
            meta_text = f"<b>URL:</b> {url}<br/><b>Datum:</b> {date}"
            story.append(Paragraph(meta_text, body_style))
            story.append(Spacer(1, 0.5 * cm))

        # Företagsbeskrivning
        desc = company.get("description", "")
        if desc:
            story.append(Paragraph("Om företaget", heading_style))
            story.append(Paragraph(desc, body_style))

        # Poängtabell
        if scores:
            story.append(Paragraph("Bedömning (1-10)", heading_style))
            score_data = [
                ["Kategori", "Poäng"],
                ["Design", str(scores.get("design", "-"))],
                ["Innehåll", str(scores.get("content", "-"))],
                ["Användbarhet", str(scores.get("usability", "-"))],
                ["Mobilvänlighet", str(scores.get("mobile", "-"))],
                ["SEO", str(scores.get("seo", "-"))],
                ["Helhetsomdöme", str(scores.get("overall", "-"))],
            ]
            t = Table(score_data, colWidths=[8 * cm, 3 * cm])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (1, 0), (1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 0.3 * cm))

        # Styrkor
        if strengths:
            story.append(Paragraph("Styrkor", heading_style))
            for s in strengths:
                story.append(Paragraph(f"• {s}", bullet_style))

        # Svagheter
        if weaknesses:
            story.append(Paragraph("Förbättringsområden", heading_style))
            for w in weaknesses:
                story.append(Paragraph(f"• {w}", bullet_style))

        # Rekommendationer
        if recommendations:
            story.append(Paragraph("Rekommendationer", heading_style))
            for r in recommendations:
                story.append(Paragraph(f"• {r}", bullet_style))

        # Footer
        story.append(Spacer(1, 1 * cm))
        footer = "Rapport genererad av SajtStudio.se"
        story.append(Paragraph(footer, body_style))

        doc.build(story)
        return True
    except Exception as e:
        print(f"⚠️  ReportLab-fel: {e}")
        return False


def generate_pdf(audit_data: Dict[str, Any], output_path: Path) -> bool:
    """
    Generera snygg PDF från audit-data.
    Försöker först WeasyPrint (snyggare), faller tillbaka på reportlab.
    """
    output_path = Path(output_path)
    
    # Försök WeasyPrint först (mycket snyggare)
    if generate_with_weasyprint(audit_data, output_path):
        print(f"✅ PDF genererad med WeasyPrint: {output_path}")
        return True
    
    # Fallback till reportlab
    if generate_with_reportlab(audit_data, output_path):
        print(f"✅ PDF genererad med ReportLab: {output_path}")
        print("💡 Tips: Installera WeasyPrint för snyggare PDF: pip install weasyprint")
        return True
    
    print("❌ Kunde inte generera PDF - installera antingen:")
    print("   pip install weasyprint  (rekommenderas - snyggare)")
    print("   pip install reportlab   (fallback)")
    return False


def main():
    """CLI för att generera PDF från JSON-fil."""
    if len(sys.argv) < 3:
        print("Användning: python generate_beautiful_pdf.py <audit_report.json> <output.pdf>")
        sys.exit(1)
    
    json_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    
    if not json_path.exists():
        print(f"❌ Filen finns inte: {json_path}")
        sys.exit(1)
    
    try:
        audit_data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Kunde inte läsa JSON: {e}")
        sys.exit(1)
    
    if generate_pdf(audit_data, pdf_path):
        print(f"✅ Klart! PDF skapad: {pdf_path}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

