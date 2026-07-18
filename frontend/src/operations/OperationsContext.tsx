import {
  createContext,
  use,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { message } from 'antd'
import { isAxiosError } from 'axios'
import {
  deleteData as apiDeleteData,
  fetchUploadStatus,
  uploadFile,
  type DeleteTarget,
} from '../api/ingestion'
import type { DeleteResult, UploadBatch, UploadStatus } from '../types'

const TERMINAL_STATUSES: UploadStatus[] = ['loaded', 'failed', 'rolled_back']
const POLL_INTERVAL_MS = 2000

interface OperationsContextValue {
  uploadBatch: UploadBatch | null
  uploading: boolean
  startUpload: (file: File, brandCode: string, productLine: string) => Promise<void>
  deleting: boolean
  startDelete: (target: DeleteTarget) => Promise<DeleteResult>
}

const OperationsContext = createContext<OperationsContextValue | null>(null)

function extractDetail(err: unknown): string | undefined {
  return isAxiosError(err) ? err.response?.data?.detail : undefined
}

// Lives above the route Outlet (mounted once in AppLayout), not inside any
// one page -- an upload's poll loop and a delete's in-flight request used to
// live in page-local state, which React tears down the instant the user
// navigates to a different page. The upload/delete itself kept running
// server-side the whole time; the user just never found out, which is
// indistinguishable from "it got cancelled" (client-reported bug,
// 2026-07-18). Moving both here means the poll loop survives navigation and
// the completion toast fires no matter which page is on screen when it
// resolves.
export function OperationsProvider({ children }: { children: ReactNode }) {
  const [uploadBatch, setUploadBatch] = useState<UploadBatch | null>(null)
  const [uploading, setUploading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const pollUntilTerminal = useCallback((batchId: number, fileName: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      let latest: UploadBatch
      try {
        latest = await fetchUploadStatus(batchId)
      } catch {
        return // transient network hiccup -- keep polling rather than give up on a blip
      }
      setUploadBatch(latest)
      if (!TERMINAL_STATUSES.includes(latest.status)) return

      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      if (latest.status === 'loaded') {
        message.success(
          latest.error_count
            ? `"${fileName}" loaded: ${latest.row_count} row(s), ${latest.error_count} rejected -- see the error report.`
            : `"${fileName}" uploaded successfully: ${latest.row_count} row(s).`,
        )
      } else if (latest.status === 'failed') {
        message.error(
          `"${fileName}" upload failed -- ${latest.failure_reason ?? 'see the error report.'}`,
        )
      }
    }, POLL_INTERVAL_MS)
  }, [])

  const startUpload = useCallback(
    async (file: File, brandCode: string, productLine: string) => {
      setUploading(true)
      setUploadBatch(null)
      try {
        const created = await uploadFile(file, brandCode, productLine)
        setUploadBatch(created)
        pollUntilTerminal(created.batch_id, file.name)
      } catch (err) {
        message.error(
          extractDetail(err) || 'Upload failed to start -- check the file and try again.',
        )
        throw err
      } finally {
        setUploading(false)
      }
    },
    [pollUntilTerminal],
  )

  const startDelete = useCallback(async (target: DeleteTarget) => {
    setDeleting(true)
    try {
      const result = await apiDeleteData(target)
      message.success(`Deleted ${result.deleted_count.toLocaleString()} row(s).`)
      return result
    } catch (err) {
      message.error(extractDetail(err) || 'Delete failed -- nothing may have changed.')
      throw err
    } finally {
      setDeleting(false)
    }
  }, [])

  return (
    <OperationsContext
      value={{ uploadBatch, uploading, startUpload, deleting, startDelete }}
    >
      {children}
    </OperationsContext>
  )
}

export function useOperations(): OperationsContextValue {
  const ctx = use(OperationsContext)
  if (!ctx) throw new Error('useOperations must be used within OperationsProvider')
  return ctx
}
