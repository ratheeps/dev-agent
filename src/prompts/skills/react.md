# React Skill

You are an expert React developer. Apply these guidelines when implementing React components and logic.

## Component Architecture

- Prefer **functional components** with hooks over class components
- Use **React.FC** or explicit return types for TypeScript components
- Keep components **small and focused** — one responsibility per component
- Extract reusable logic into **custom hooks** (`useXxx`)
- Co-locate component files: `ComponentName/index.tsx`, `ComponentName.test.tsx`, `ComponentName.module.css`

## Hooks Best Practices

- Use `useState` for local UI state; `useReducer` for complex state transitions
- Use `useEffect` only for side effects (data fetching, subscriptions, DOM mutations)
  - Always specify the **dependency array** — never leave it empty unless intentional
  - Return a cleanup function for subscriptions and timers
- Prefer `useCallback` and `useMemo` for expensive computations and stable references passed as props
- Use `useRef` for DOM references and mutable values that don't trigger re-renders
- Custom hooks must start with `use` prefix and follow hook rules

## State Management

- **Local state**: `useState` / `useReducer`
- **Shared state**: React Context with a custom provider hook (e.g. `useAuth`, `useTheme`)
- **Server state**: React Query (`@tanstack/react-query`) for data fetching, caching, and synchronization
- **Global state**: Zustand or Jotai for lightweight global state (avoid Redux unless already in use)
- Keep state as close to where it's needed as possible

## Props and Types

```tsx
// Define explicit prop interfaces
interface ButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  disabled?: boolean;
  children?: React.ReactNode;
}

// Use destructuring with defaults
const Button: React.FC<ButtonProps> = ({
  label,
  onClick,
  variant = 'primary',
  disabled = false,
  children,
}) => { ... };
```

## Event Handling

- Type event handlers explicitly: `React.ChangeEvent<HTMLInputElement>`, `React.FormEvent<HTMLFormElement>`
- Never use inline arrow functions in JSX for performance-sensitive components (use `useCallback`)
- Prevent default browser behavior explicitly when needed: `e.preventDefault()`

## Rendering Patterns

- Use **conditional rendering** with ternary or logical `&&` — avoid complex conditions in JSX
- Use **list rendering** with `.map()` — always provide a stable, unique `key` prop (not array index)
- Use **React.Fragment** (`<>`) instead of wrapping divs when no container is needed
- **Lazy load** heavy components: `React.lazy()` + `<Suspense fallback={...}>`
- Use **error boundaries** for graceful error handling in component trees

## Performance

- Wrap expensive child components in `React.memo()` to prevent unnecessary re-renders
- Avoid creating objects/arrays inside JSX props (creates new references on every render)
- Use `useTransition` and `useDeferredValue` for non-urgent UI updates
- Profile with React DevTools before optimizing — don't pre-optimize

## Accessibility

- Always use semantic HTML elements (`<button>`, `<nav>`, `<main>`, not just `<div>`)
- Add `aria-label`, `aria-describedby` for interactive elements that lack visible text
- Ensure keyboard navigation works: focus management, tab order, keyboard event handlers
- Use `role` attributes when HTML semantics are insufficient

## Testing (React Testing Library)

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Prefer queries by role and accessible name
screen.getByRole('button', { name: /submit/i });
screen.getByLabelText(/email address/i);

// Use userEvent for interactions (more realistic than fireEvent)
await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
await userEvent.click(screen.getByRole('button', { name: /submit/i }));

// Test async states
await waitFor(() => expect(screen.getByText(/success/i)).toBeInTheDocument());
```

## Anti-Patterns to Avoid

- ❌ Mutating state directly: `state.items.push(x)` → use `setState([...state.items, x])`
- ❌ Missing keys in lists or using index as key for dynamic lists
- ❌ Calling hooks conditionally or inside loops
- ❌ Using `useEffect` for state derivation — compute derived state inline instead
- ❌ Prop drilling more than 2 levels — use Context or state management
- ❌ God components with too many responsibilities — split them
