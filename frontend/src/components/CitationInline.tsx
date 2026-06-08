/** Inline citation reference shown inside analyst output. */

interface CitationInlineProps {
  index: number;
  title: string;
  url: string | null;
}

export function CitationInline({ index, title, url }: CitationInlineProps) {
  const content = (
    <span
      title={title}
      className={`inline-flex items-center gap-1 ${url ? 'cursor-pointer' : 'cursor-help'}`}
    >
      <span className="badge badge-sm badge-primary">{index}</span>
    </span>
  );

  if (url) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" title={title} className="no-underline">
        {content}
      </a>
    );
  }
  return <span title={title}>{content}</span>;
}
