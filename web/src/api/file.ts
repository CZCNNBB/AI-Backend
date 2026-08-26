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
  file_ids: string[]
}

/** 批量上传原始文件；接口只负责保存并返回 file_id，不执行内容解析。 */
export function uploadFiles(files: File[]): Promise<FileUploadResponse> {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  return http.post<unknown, FileUploadResponse>('/file/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 文件内容源解析响应；供 Agent 附件等需要立即读取文件的业务场景使用。 */
export interface FileParseResponse {
  file_id: string
  original_name: string
  content_type: string
  conversion_status: string
}

/** 根据 file_id 显式构建可读内容源。 */
export function parseUploadedFile(fileId: string): Promise<FileParseResponse> {
  return http.post<unknown, FileParseResponse>('/file/parse', {
    file_id: fileId,
    force: false,
  })
}

/** 删除尚未发送给 Agent 的临时上传文件。 */
export function deleteAgentFiles(fileIds: string[]): Promise<{ deleted: number; file_ids: string[] }> {
  return http.post('/file/delete', { file_ids: fileIds })
}
