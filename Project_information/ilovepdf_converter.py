import requests

def ilovepdf_pdf_to_word(public_key, pdf_path, output_docx_path):
    print("1. Authenticating & Starting Task...")
    headers = {"Authorization": f"Bearer {public_key}"}
    
    # Tell the API we want to use the 'pdfword' tool
    start_resp = requests.post("https://api.ilovepdf.com/v1/start/pdfword", headers=headers).json()
    if 'server' not in start_resp:
        raise Exception(f"Failed to start task. Check your API key. Response: {start_resp}")
        
    server_url = f"https://{start_resp['server']}/v1"
    task_id = start_resp['task']
    
    print("2. Uploading PDF file to server...")
    with open(pdf_path, 'rb') as f:
        upload_resp = requests.post(
            f"{server_url}/upload", 
            headers=headers, 
            data={'task': task_id}, 
            files={'file': f}
        ).json()
    server_filename = upload_resp['server_filename']
    
    print("3. Processing the file (Converting to Word)...")
    process_data = {
        'task': task_id,
        'tool': 'pdfword',
        'files[0][server_filename]': server_filename,
        'files[0][filename]': 'document.pdf' 
    }
    # This request triggers the conversion engine
    requests.post(f"{server_url}/process", headers=headers, data=process_data)
    
    print("4. Downloading the converted Word Document...")
    download_resp = requests.get(f"{server_url}/download/{task_id}", headers=headers)
    
    # Save the downloaded binary data as a .docx file
    with open(output_docx_path, 'wb') as f:
        f.write(download_resp.content)
        
    print(f"✅ Success! Saved to {output_docx_path}")

if __name__ == "__main__":
    # Get this from your account dashboard at developer.ilovepdf.com
    MY_PUBLIC_KEY = "project_public_805e15f828f8893c02ed159fdcac28f4_vjlWx5589efba485e4f10c40bd7d0af46d7a0" 
    
    ilovepdf_pdf_to_word(MY_PUBLIC_KEY, "D:\Projects\SIMBA-RUNBOOKS\PPFPB_Runbook\Project_information\PPF-The-Purple-Book-2024-22-24.pdf", "output.docx")