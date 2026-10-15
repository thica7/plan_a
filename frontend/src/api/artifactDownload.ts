import { downloadArtifact } from './client';
import type { ArtifactRecord } from './types';

export async function saveArtifactDownload(artifact: ArtifactRecord, isCurrent = () => true): Promise<void> {
  if (!isCurrent()) return;
  const blob = await downloadArtifact(artifact.id);
  if (!isCurrent()) return;
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  try {
    link.href = objectUrl;
    link.download = artifact.filename;
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }
}
