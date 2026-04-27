from pdf2docx import Converter

pdf_file = 'D:\Projects\SIMBA-RUNBOOKS\PPFPB_Runbook\Project_information\PPF-The-Purple-Book-2024-22-24.pdf'
docx_file = 'output.docx'

# Convert PDF to Word
cv = Converter(pdf_file)
cv.convert(docx_file, start=0, end=None) # All pages
cv.close()