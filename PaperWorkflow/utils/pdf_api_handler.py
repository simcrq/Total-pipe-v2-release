import os
import time
import json
import zipfile
import requests
from loguru import logger


class _TerminalFailure(RuntimeError):
    """A failure that polling again cannot fix."""


def _safe_extract(zip_path, destination):
    """Extract a downloaded archive, refusing members that escape ``destination`` (Zip Slip)."""
    root = os.path.realpath(destination)
    with zipfile.ZipFile(zip_path, 'r') as archive:
        for member in archive.infolist():
            target = os.path.realpath(os.path.join(root, member.filename))
            if target != root and not target.startswith(root + os.sep):
                raise ValueError(f"Unsafe path in MinerU archive: {member.filename!r}")
        archive.extractall(root)


class ApiPDFProcessor:
    def __init__(self, config):
        self.config = config

    def process(self, pdf_path, output_dir):
        """
        使用 MinerU API 转换
        pdf_path: PDF文件绝对路径
        output_dir: 输出的根目录
        """
        file_name = os.path.basename(pdf_path).replace('.pdf', '')
        abs_output_dir = os.path.abspath(output_dir).replace('\\', '/')
        
        # 为了与 Local 模式行为一致，API 模式也将结果放入 file_name 子目录
        target_dir = os.path.join(abs_output_dir, file_name)
        os.makedirs(target_dir, exist_ok=True)
        
        api_config = self.config['api']['mineru']
        api_key = api_config['api_key']
        # The legacy adapter uses the official batch-file endpoint directly.
        upload_url_endpoint = (
            api_config.get('upload_url')
            or api_config.get('api_url')
            or 'https://mineru.net/api/v4/file-urls/batch'
        )
        request_timeout = int(api_config.get('request_timeout', 120))

        header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        # 1. 获取上传 URL
        data_id = file_name 
        data = {
            "files": [
                {"name": f"{file_name}.pdf", "data_id": data_id}
            ],
            "model_version": "vlm"
        }
        
        logger.info(f"第1/2步:Requesting upload URL for {file_name}...")
        response = requests.post(
            upload_url_endpoint, headers=header, json=data, timeout=request_timeout
        )
        
        if response.status_code != 200:
            logger.error(f"Failed to get upload URL: {response.text}")
            raise Exception(f"API Request Failed: {response.status_code}")
        
        result = response.json()
        if result.get("code") != 0:
            raise Exception(f"Get Upload URL Failed: {result.get('msg')}")

        batch_id = result["data"]["batch_id"]
        file_urls = result["data"]["file_urls"]
        
        if not file_urls:
             raise Exception("No upload URLs returned")
        
        upload_url = file_urls[0]
        logger.info(f"Got batch_id: {batch_id}. Uploading to: {upload_url[:30]}...")

        # 2. 上传文件
        with open(pdf_path, 'rb') as f:
            res_upload = requests.put(upload_url, data=f, timeout=request_timeout)
            if res_upload.status_code != 200:
                raise Exception(f"Upload failed: {res_upload.text}")
        
        logger.info("文件上传成功. 开始获取任务情况...")
        # The official batch-file endpoint automatically submits extraction
        # after the signed PUT succeeds; there is no second submit request.
        # 3. 轮询并下载结果
        self._poll_result(batch_id, file_name, target_dir, header)

    def _poll_result(self, batch_id, file_name, output_path, header):
        api_config = self.config['api']['mineru']
        max_retries = int(api_config.get('max_poll_retries', 60))
        polling_base = api_config.get(
            'polling_url', 'https://mineru.net/api/v4/extract-results/batch'
        ).rstrip('/')
        polling_url = f"{polling_base}/{batch_id}"
        
        # 获取轮询间隔，默认 6 秒
        interval = self.config['api']['mineru'].get('polling_interval', 6)
        
        succeeded = False
        
        for attempt in range(max_retries):
            time.sleep(interval)
            logger.info(f"{interval}s 尝试提取batch {batch_id}中md，第 {attempt+1}/{max_retries} 次...")
            
            try:
                poll_res = requests.get(
                    polling_url,
                    headers=header,
                    timeout=int(api_config.get('request_timeout', 120)),
                )
                if poll_res.status_code != 200:
                     logger.warning(f"Polling failed with status {poll_res.status_code}")
                     continue
                
                poll_data = poll_res.json()
                if poll_data.get("code") != 0:
                    logger.warning(f"Polling returned error code: {poll_data.get('msg')}")
                    continue

                # The poll response carries signed download URLs; it is never written to disk.

                data = poll_data.get("data", {})
                extract_results = data.get("extract_result", [])
                
                if extract_results:
                    target_result = None
                    for res in extract_results:
                        if file_name in res.get("file_name", "") or len(extract_results) == 1:
                            target_result = res
                            break
                    
                    if target_result:
                        state = target_result.get("state")
                        if state == "failed":
                            raise _TerminalFailure(
                                f"MinerU extraction failed for {file_name}: "
                                f"{target_result.get('err_msg', 'unknown error')}"
                            )
                        if state == "done":
                            full_zip_url = target_result.get("full_zip_url")
                            markdown_url = target_result.get("markdown_url")
                            
                            dl_url = markdown_url if markdown_url else full_zip_url
                            
                            if dl_url:
                                logger.info(f"提取成功!正在下载 {dl_url[:30]}...")
                                dl_res = requests.get(
                                    dl_url,
                                    timeout=int(api_config.get('request_timeout', 120)),
                                )
                                dl_res.raise_for_status()
                                
                                if dl_url.endswith(".zip") or "zip" in dl_url:
                                     zip_path = os.path.join(output_path, f"{file_name}_result.zip")
                                     with open(zip_path, 'wb') as f:
                                         f.write(dl_res.content)
                                     
                                     logger.info(f"已保存zip结果到 {zip_path}。正在解压...")
                                     try:
                                         _safe_extract(zip_path, output_path)
                                         succeeded = True
                                     except zipfile.BadZipFile as e:
                                         logger.error(f"Failed to unzip: {e}")
                                     except ValueError as e:
                                         # An unsafe archive is a hard failure, not something to retry.
                                         raise _TerminalFailure(str(e)) from e
                                else:
                                     md_file_path = os.path.join(output_path, f"{file_name}.md")
                                     with open(md_file_path, 'wb') as f:
                                         f.write(dl_res.content)
                                     succeeded = True
                                break
                        else:
                            logger.info(f"Task state: {state}")
                else:
                     logger.info("Waiting for extract_result...")

            except _TerminalFailure:
                raise
            except Exception as e:
                logger.warning(f"Polling exception: {e}")
                continue
            
            if succeeded:
                break

        if not succeeded:
             logger.warning("Polling timed out or failed. Check debug logs.")
             raise TimeoutError(
                 f"MinerU extraction did not finish after {max_retries} polls for {file_name}"
             )
