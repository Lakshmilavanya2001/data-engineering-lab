# Re-rendering the lab guide

    python3 -m venv venv && venv/bin/pip install python-docx pillow playwright pymupdf
    # Chromium for the PDF: `venv/bin/playwright install chromium`, or point render.py at an existing one
    venv/bin/python render.py        # writes ../Lab18_Data_Engineering_Pipeline_Lab_Guide.{docx,html,pdf}

- content.py  = the whole guide as a list of blocks; code cells are pulled live from
                ../../notebooks/Lab18_Train_Churn_Model.ipynb so they never drift.
- render.py   = builds the .docx on hpe_arial_a4_base.docx (HPE Arial A4 template, instructional
                content removed, header/footer set to "Lab guide" / training disclosure) and an
                HTML twin rendered to PDF with headless Chromium (A4, same footer).
- Figures are read from ../shots/NN_*.png; a missing file renders as a labelled placeholder box.
- Fonts: the PDF uses Arial when installed, else Liberation Sans (metric-compatible).
