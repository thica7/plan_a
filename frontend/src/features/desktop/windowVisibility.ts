import { createContext } from 'react';

// Standalone business routes remain visible without a desktop window provider.
export const WindowVisibilityContext = createContext(true);
