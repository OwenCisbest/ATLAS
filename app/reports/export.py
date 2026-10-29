import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from app.security.privacy import minimize


def clean(value):
    if isinstance(value, dict):
        return {k: v if k in {'id', 'investigation_id', 'source_id', 'target_id', 'evidence_id', 'source_url', 'retrieved_at', 'created', 'modified', 'discovered'} else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return minimize(value) if isinstance(value, str) else value


def export(data: dict, path: Path, format: str):
    # Export only selected fields. Credentials, API payloads and search queries are excluded.
    inv = data['investigation']
    payload = {'investigation': {k: inv[k] for k in ('id', 'title', 'description', 'scope', 'notes', 'created', 'modified')},
               'evidence': data['evidence'], 'relationships': data['relationships'],
               'limitations': 'Confidence grades are heuristic, not probabilities. Unverified matches are separate records. '
               'Sources can change; confirmation is a researcher assessment, not independent certification.'}
    payload = clean(payload)
    if format == 'json':
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), 'utf-8')
    elif format == 'csv':
        fields = ['id', 'title', 'entity_type', 'provider', 'source_url', 'retrieved_at', 'summary', 'status', 'tags', 'notes']
        with path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in payload['evidence']:
                # Prevent spreadsheet formula execution.
                writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v
                                 for k, v in row.items()})
    elif format == 'pdf':
        styles = getSampleStyleSheet()
        font_dir = Path(__file__).parent / 'fonts'
        for name, filename in [('Atlas', 'DejaVuSans.ttf'), ('AtlasBold', 'DejaVuSans-Bold.ttf')]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
        for style in styles.byName.values():
            style.fontName = 'AtlasBold' if style.name.startswith(('Heading', 'Title')) else 'Atlas'
        styles['BodyText'].wordWrap = 'CJK'
        story = []

        def para(text, style='BodyText'):
            story.append(Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style]))
            story.append(Spacer(1, 6))

        para('ATLAS · PUBLIC RESEARCH REPORT', 'Title')
        para(payload['investigation']['title'], 'Heading1')
        para('Scope', 'Heading2')
        para(payload['investigation']['scope'])
        para('Executive summary', 'Heading2')
        para(f"{len(payload['evidence'])} source records and {len(payload['relationships'])} documented or proposed relationships.")
        para(payload['investigation']['description'])
        para('Methodology & limitations', 'Heading2')
        para('Public API research and researcher annotations. No intrusive scanning. Each finding retains its source and retrieval date.')
        para(payload['limitations'])
        para('Researcher notes (not independently verified)', 'Heading2')
        para(payload['investigation']['notes'])
        para('Findings & entity profiles', 'Heading2')
        for row in payload['evidence']:
            para(f"[{row['id']}] {row['title']}", 'Heading3')
            para(f"{row['entity_type']} · {row['provider']} · {row['status'].upper()}")
            para(row['summary'])
            para(row['details'])
            para(f"Source: {row['source_url']}\nRetrieved: {row['retrieved_at']}")
            if row['notes']:
                para('Researcher notes: ' + row['notes'])
        para('Relationship analysis', 'Heading2')
        for row in payload['relationships']:
            para(f"{row['source_id']} → {row['target_id']}: {row['label']} ({row['status']}; grade {row['confidence']}/100)")
            para(row['explanation'] + '\nEvidence: ' + row['evidence_id'])
        SimpleDocTemplate(str(path), rightMargin=0.65*inch, leftMargin=0.65*inch,
                          title=inv['title'], author='ATLAS').build(story)
    else:
        raise ValueError('Unsupported export format')
