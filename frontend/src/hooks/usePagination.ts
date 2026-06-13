import { useState, useEffect } from 'react'

export function usePagination<T>(items: T[], defaultPageSize = 25) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(defaultPageSize)

  // Reset to page 1 whenever the data set changes (search / filter applied)
  const len = items.length
  useEffect(() => { setPage(1) }, [len])

  const total      = items.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const safePage   = Math.min(page, totalPages)
  const start      = (safePage - 1) * pageSize
  const paged      = items.slice(start, start + pageSize)

  return { page: safePage, setPage, pageSize, setPageSize, totalPages, paged, total }
}
