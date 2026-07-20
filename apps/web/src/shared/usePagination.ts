import { useEffect, useMemo, useState } from "react";

export const DEFAULT_PAGE_SIZE = 20;

const EMPTY: readonly never[] = [];

export type PaginationState<T> = {
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  total: number;
  pageCount: number;
  view: T[];
  from: number;
  to: number;
};

/** Client-side page slice. Resets to page 0 when length / pageSize / resetKey changes. */
export function usePagination<T>(
  items: readonly T[] | null | undefined,
  pageSize: number = DEFAULT_PAGE_SIZE,
  resetKey?: string | number | null,
): PaginationState<T> {
  const list = items ?? (EMPTY as readonly T[]);
  const [page, setPage] = useState(0);
  const total = list.length;

  useEffect(() => {
    setPage(0);
  }, [total, pageSize, resetKey]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize) || 1);
  const safePage = Math.min(Math.max(0, page), pageCount - 1);
  const from = total === 0 ? 0 : safePage * pageSize + 1;
  const to = Math.min(total, (safePage + 1) * pageSize);

  const view = useMemo(
    () => list.slice(safePage * pageSize, safePage * pageSize + pageSize) as T[],
    [list, safePage, pageSize],
  );

  return {
    page: safePage,
    setPage,
    pageSize,
    total,
    pageCount,
    view,
    from,
    to,
  };
}
