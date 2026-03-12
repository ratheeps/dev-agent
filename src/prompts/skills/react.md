# React Skill

You are an expert React developer. Apply these guidelines when implementing React components and logic.
This project uses **React 18**, **Next.js 14 App Router**, **TypeScript**, **Tailwind CSS**, **shadcn/ui**, and **Redux Toolkit**.

## Component Architecture

- Prefer **functional components** with hooks — never class components
- Use explicit TypeScript return types: `React.FC<Props>` or `: JSX.Element`
- Keep components **small and focused** — one responsibility per component
- Extract reusable logic into **custom hooks** (`useXxx` in `src/hooks/`)
- Directory structure: `src/components/ui/` for shadcn primitives, `src/components/` for feature components, `src/features/<domain>/` for feature slices

## Component Library: shadcn/ui + Tailwind CSS

The project uses **shadcn/ui** with Radix UI primitives. Always use existing UI components before building custom ones.

```tsx
// ✅ Use shadcn/ui components from @/components/ui/
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

// Icons from lucide-react
import { Loader2, CheckCircle, AlertCircle, ChevronRight } from 'lucide-react';

// Utility for conditional class names
import { cn } from '@/lib/utils';

// Component with Tailwind + cn utility
interface AlertProps {
  type: 'success' | 'error' | 'warning';
  message: string;
  className?: string;
}

export function Alert({ type, message, className }: AlertProps): JSX.Element {
  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-md p-3 text-sm',
        type === 'success' && 'bg-green-50 text-green-800',
        type === 'error' && 'bg-red-50 text-red-800',
        type === 'warning' && 'bg-yellow-50 text-yellow-800',
        className,
      )}
    >
      {type === 'success' && <CheckCircle className="h-4 w-4" />}
      {type === 'error' && <AlertCircle className="h-4 w-4" />}
      <span>{message}</span>
    </div>
  );
}
```

## Form Handling: react-hook-form + Zod

Always use **react-hook-form** with **Zod** validation via `@hookform/resolvers/zod`.

```tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

// 1. Define Zod schema
const loginSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

type LoginFormData = z.infer<typeof loginSchema>;

// 2. Use in component
export function LoginForm({ onSubmit }: { onSubmit: (data: LoginFormData) => Promise<void> }): JSX.Element {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const handleFormSubmit = async (data: LoginFormData) => {
    try {
      await onSubmit(data);
    } catch (error) {
      setError('root', { message: 'Invalid credentials. Please try again.' });
    }
  };

  return (
    <form onSubmit={handleSubmit(handleFormSubmit)} className="space-y-4">
      <div className="space-y-1">
        <Label htmlFor="email">Email</Label>
        <Input id="email" type="email" {...register('email')} aria-invalid={!!errors.email} />
        {errors.email && <p className="text-sm text-red-600">{errors.email.message}</p>}
      </div>
      <div className="space-y-1">
        <Label htmlFor="password">Password</Label>
        <Input id="password" type="password" {...register('password')} />
        {errors.password && <p className="text-sm text-red-600">{errors.password.message}</p>}
      </div>
      {errors.root && <p className="text-sm text-red-600">{errors.root.message}</p>}
      <Button type="submit" disabled={isSubmitting} className="w-full">
        {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        Sign in
      </Button>
    </form>
  );
}
```

## State Management: Redux Toolkit

Global state uses **Redux Toolkit** (`@reduxjs/toolkit`) with `react-redux` and `redux-persist`.

```tsx
// src/store/slices/authSlice.ts
import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';

interface AuthState {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
}

const initialState: AuthState = { user: null, token: null, isLoading: false, error: null };

// Async thunk for API calls
export const loginUser = createAsyncThunk(
  'auth/login',
  async (credentials: LoginCredentials, { rejectWithValue }) => {
    try {
      const response = await authService.login(credentials);
      return response.data;
    } catch (error) {
      return rejectWithValue(error instanceof ApiError ? error.message : 'Login failed');
    }
  },
);

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    logout: (state) => {
      state.user = null;
      state.token = null;
    },
    setToken: (state, action: PayloadAction<string>) => {
      state.token = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loginUser.pending, (state) => { state.isLoading = true; state.error = null; })
      .addCase(loginUser.fulfilled, (state, action) => {
        state.isLoading = false;
        state.user = action.payload.user;
        state.token = action.payload.token;
      })
      .addCase(loginUser.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });
  },
});

export const { logout, setToken } = authSlice.actions;
export default authSlice.reducer;

// Typed selectors
export const selectCurrentUser = (state: RootState) => state.auth.user;
export const selectAuthToken = (state: RootState) => state.auth.token;

// Usage in component
function ProfileButton(): JSX.Element {
  const user = useAppSelector(selectCurrentUser);
  const dispatch = useAppDispatch();
  return (
    <Button variant="ghost" onClick={() => dispatch(logout())}>
      {user?.name}
    </Button>
  );
}
```

## API Service Layer: Axios

API calls go through typed service classes in `src/services/`. Never call `fetch` or `axios` directly in components.

```tsx
// src/services/api.ts — Base Axios instance
import axios, { AxiosError } from 'axios';

export const apiClient = axios.create({
  baseURL: process.env.NEXT_APP_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
});

// Request interceptor — attach token
apiClient.interceptors.request.use((config) => {
  const token = store.getState().auth.token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor — handle 401
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      store.dispatch(logout());
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

// src/services/userService.ts — Typed service
interface UserProfile { id: string; name: string; email: string; }

export const userService = {
  async getProfile(): Promise<UserProfile> {
    const { data } = await apiClient.get<{ data: UserProfile }>('/api/v1/user/profile');
    return data.data;
  },
  async updateProfile(payload: Partial<UserProfile>): Promise<UserProfile> {
    const { data } = await apiClient.patch<{ data: UserProfile }>('/api/v1/user/profile', payload);
    return data.data;
  },
};
```

## Hooks Best Practices

- `useState` — local UI state; `useReducer` — complex state machines
- `useEffect` — side effects only; always specify the dependency array; return cleanup
- `useCallback` — stable function references passed as props; `useMemo` — expensive computations
- `useRef` — DOM refs and mutable values that must not trigger re-renders
- Custom hooks in `src/hooks/`:

```tsx
// src/hooks/useAsync.ts — Generic async state hook
function useAsync<T>(asyncFn: () => Promise<T>, deps: React.DependencyList) {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    asyncFn()
      .then((data) => { if (!cancelled) setState({ data, loading: false, error: null }); })
      .catch((err) => { if (!cancelled) setState({ data: null, loading: false, error: err.message }); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
```

## Props and Types

```tsx
// Define explicit prop interfaces — always export
export interface ButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'default' | 'destructive' | 'outline' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  disabled?: boolean;
  children?: React.ReactNode;
  className?: string;
}

// Use destructuring with defaults
export function ActionButton({
  label,
  onClick,
  variant = 'default',
  loading = false,
  disabled = false,
  className,
}: ButtonProps): JSX.Element {
  return (
    <Button
      variant={variant}
      onClick={onClick}
      disabled={disabled || loading}
      className={className}
    >
      {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
      {label}
    </Button>
  );
}
```

## Loading and Error States

Always handle loading, error, and empty states explicitly:

```tsx
function ProductList(): JSX.Element {
  const { data: products, loading, error } = useAsync(() => productService.list(), []);

  if (loading) return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  );

  if (error) return (
    <Alert type="error" message={error} className="my-4" />
  );

  if (!products?.length) return (
    <p className="text-center text-muted-foreground py-12">No products found.</p>
  );

  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {products.map((product) => (
        <li key={product.id}><ProductCard product={product} /></li>
      ))}
    </ul>
  );
}
```

## Rendering Patterns

- Use ternary or logical `&&` for conditional rendering — avoid complex conditions in JSX
- Use `.map()` with stable, unique `key` props (use `id`, never array index for dynamic lists)
- Use `<>` (React.Fragment) instead of wrapping divs
- `React.lazy()` + `<Suspense>` for code-split heavy components
- `React.memo()` for expensive child components that receive stable props

## Accessibility

- Always use semantic HTML: `<button>`, `<nav>`, `<main>`, `<article>`, `<section>`
- Add `aria-label` / `aria-describedby` for interactive elements without visible text
- Ensure keyboard navigation: focus management, tab order, `onKeyDown` handlers
- Use `role` attributes when semantic HTML is insufficient
- shadcn/ui components have built-in ARIA — don't break accessibility by wrapping in non-semantic elements

## Testing (React Testing Library)

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { store } from '@/store';

// Wrap with Redux Provider when testing connected components
function renderWithStore(ui: React.ReactElement) {
  return render(<Provider store={store}>{ui}</Provider>);
}

describe('LoginForm', () => {
  it('shows validation error for invalid email', async () => {
    renderWithStore(<LoginForm onSubmit={vi.fn()} />);
    await userEvent.type(screen.getByLabelText(/email/i), 'not-an-email');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() =>
      expect(screen.getByText(/invalid email/i)).toBeInTheDocument()
    );
  });
});
```

## Anti-Patterns to Avoid

- ❌ Calling APIs directly in components — use service layer (`src/services/`)
- ❌ Mutating state directly: `state.items.push(x)` → use Redux Toolkit or spread
- ❌ Using array index as `key` in dynamic lists
- ❌ Calling hooks conditionally or inside loops
- ❌ Using `useEffect` for state derivation — compute derived state inline
- ❌ Prop drilling more than 2 levels — use Redux or Context
- ❌ Using `any` type — use proper TypeScript interfaces
- ❌ Inline styles when Tailwind classes exist
- ❌ Building custom UI primitives when shadcn/ui components are available
- ❌ Missing `aria-*` attributes on interactive elements
