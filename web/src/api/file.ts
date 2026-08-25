/**
 * 文件服务接口。
 * 用于 Agent 调用页上传附件，并把服务端返回的 file_id 传给 /agent/messages。
 */
import http from './http'

/** 已上传文件的服务端视图。 */
export interface UploadedFileView {
  file_id: string
  original_name: string
  extension?: string
  mime_type?: string | null
  size_bytes?: number
  status?: string
  content_type?: string
  conversion_status?: string
}

/** 文件上传接口返回。 */
export interface FileUploadResponse {
  files: UploadedFileView[]
}

/** 批量上传文件并等待服务端完成内容源构建。 */
export function uploadAgentFiles(files: File[]): Promise<FileUploadResponse> {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  return http.post<unknown, FileUploadResponse>('/file/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 删除尚未发送给 Agent 的临时上传文件。 */
export function deleteAgentFiles(fileIds: string[]): Promise<{ deleted: number; file_ids: string[] }> {
  return http.post('/file/delete', { file_ids: fileIds })
}
