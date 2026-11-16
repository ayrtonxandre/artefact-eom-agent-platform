import os
import sys
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eom_agent.workspace_service import get_slides_service

svc = get_slides_service()
template_id = "1DH-zXzB9CmaYB-p0CyXJDR-gdeJ6gSvylM-76IPfkEY"

setup_reqs = [
    # 1. Insert text in client badge box
    {
        "insertText": {
            "objectId": "h772f8610822c3afb_1_156",
            "text": "{{CLIENT_TAG}}",
            "insertionIndex": 0
        }
    },
    {
        "updateTextStyle": {
            "objectId": "h772f8610822c3afb_1_156",
            "textRange": {"type": "ALL"},
            "style": {
                "fontFamily": "Roboto",
                "fontSize": {"magnitude": 11, "unit": "PT"},
                "bold": True,
                "foregroundColor": {"opaqueColor": {"rgbColor": {"red": 0.05, "green": 0.1, "blue": 0.25}}}
            },
            "fields": "fontFamily,fontSize,bold,foregroundColor"
        }
    },
    {
        "updateParagraphStyle": {
            "objectId": "h772f8610822c3afb_1_156",
            "textRange": {"type": "ALL"},
            "style": {"alignment": "CENTER"},
            "fields": "alignment"
        }
    },
    # 2. Insert text in tech badge box
    {
        "insertText": {
            "objectId": "h772f8610822c3afb_1_155",
            "text": "{{TECH_TAG}}",
            "insertionIndex": 0
        }
    },
    {
        "updateTextStyle": {
            "objectId": "h772f8610822c3afb_1_155",
            "textRange": {"type": "ALL"},
            "style": {
                "fontFamily": "Roboto",
                "fontSize": {"magnitude": 11, "unit": "PT"},
                "bold": True,
                "foregroundColor": {"opaqueColor": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}}
            },
            "fields": "fontFamily,fontSize,bold,foregroundColor"
        }
    },
    {
        "updateParagraphStyle": {
            "objectId": "h772f8610822c3afb_1_155",
            "textRange": {"type": "ALL"},
            "style": {"alignment": "CENTER"},
            "fields": "alignment"
        }
    },
    # 3. Style rectangle h772f8610822c3afb_1_172 (the right visual container) to sleek Artefact card background
    {
        "updateShapeProperties": {
            "objectId": "h772f8610822c3afb_1_172",
            "shapeProperties": {
                "shapeBackgroundFill": {
                    "solidFill": {
                        "color": {"rgbColor": {"red": 0.96, "green": 0.965, "blue": 0.98}},
                        "alpha": 1.0
                    }
                },
                "outline": {
                    "outlineFill": {
                        "solidFill": {
                            "color": {"rgbColor": {"red": 0.88, "green": 0.89, "blue": 0.92}},
                            "alpha": 1.0
                        }
                    },
                    "weight": {"magnitude": 9525, "unit": "EMU"}
                }
            },
            "fields": "shapeBackgroundFill,outline"
        }
    },
    # 4. Create right card text box for Quadrant 4 / Architecture / Next Steps
    {
        "createShape": {
            "objectId": "q4_right_container_text",
            "shapeType": "TEXT_BOX",
            "elementProperties": {
                "pageObjectId": "h772f8610822c3afb_1_142",
                "size": {
                    "width": {"magnitude": 3100000, "unit": "EMU"},
                    "height": {"magnitude": 1700000, "unit": "EMU"}
                },
                "transform": {
                    "scaleX": 1.0,
                    "scaleY": 1.0,
                    "translateX": 5150000,
                    "translateY": 1750000,
                    "unit": "EMU"
                }
            }
        }
    },
    {
        "insertText": {
            "objectId": "q4_right_container_text",
            "text": "{{CARD_4_HEADER}}\n\n{{RECOMMENDATIONS}}",
            "insertionIndex": 0
        }
    },
    {
        "updateTextStyle": {
            "objectId": "q4_right_container_text",
            "textRange": {"type": "ALL"},
            "style": {
                "fontFamily": "Roboto",
                "fontSize": {"magnitude": 9.5, "unit": "PT"},
                "foregroundColor": {"opaqueColor": {"rgbColor": {"red": 0.05, "green": 0.1, "blue": 0.25}}}
            },
            "fields": "fontFamily,fontSize,foregroundColor"
        }
    }
]

try:
    svc.presentations().batchUpdate(presentationId=template_id, body={"requests": setup_reqs}).execute()
    print("Setup requests executed successfully.")
except Exception as e:
    print("Setup error:", e)
