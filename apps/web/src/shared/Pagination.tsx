type Props = {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
  /** Hide when a single page fits all rows (default true). */
  hideIfSinglePage?: boolean;
};

/** Compact prev/next pager for client-sliced tables. */
export function Pagination({
  page,
  pageSize,
  total,
  onChange,
  hideIfSinglePage = true,
}: Props) {
  if (total <= 0) return null;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (hideIfSinglePage && pageCount <= 1) return null;

  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  const canPrev = page > 0;
  const canNext = page < pageCount - 1;

  return (
    <div className="pager" role="navigation" aria-label="分页">
      <span className="pager-meta mono">
        {from}–{to} / {total}
      </span>
      <div className="pager-btns">
        <button
          type="button"
          className="btn ghost pager-btn"
          disabled={!canPrev}
          onClick={() => onChange(page - 1)}
          aria-label="上一页"
        >
          上一页
        </button>
        <span className="pager-page mono">
          {page + 1} / {pageCount}
        </span>
        <button
          type="button"
          className="btn ghost pager-btn"
          disabled={!canNext}
          onClick={() => onChange(page + 1)}
          aria-label="下一页"
        >
          下一页
        </button>
      </div>
    </div>
  );
}
