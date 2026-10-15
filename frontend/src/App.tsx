import { useEffect, useMemo, useState } from 'react'
import './App.css'

type Product = {
  id: number
  name: string
  sku: string
  category: string
  description: string
  price: number
  stock: number
  is_active: boolean
}

type User = {
  id: number
  email: string
  role: string
}

type Analytics = {
  total_sales: number
  user_signups: number
  order_logs: Array<Record<string, unknown>>
  order_status_summary: Array<Record<string, unknown>>
  transaction_status_summary: Array<Record<string, unknown>>
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
    },
  })

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.text()

  if (!response.ok) {
    const message = typeof payload === 'string' ? payload : payload?.detail || payload?.message || 'Request failed'
    throw new Error(message)
  }

  return payload as T
}

function App() {
  const [token, setToken] = useState<string>(() => localStorage.getItem('saas-token') || '')
  const [user, setUser] = useState<User | null>(() => {
    const raw = localStorage.getItem('saas-user')
    return raw ? (JSON.parse(raw) as User) : null
  })
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [authForm, setAuthForm] = useState({ email: '', password: '' })
  const [authError, setAuthError] = useState('')
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [productsError, setProductsError] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [page, setPage] = useState(1)
  const [pageCount, setPageCount] = useState(1)
  const [cart, setCart] = useState<Record<number, number>>({})
  const [checkoutMessage, setCheckoutMessage] = useState('')
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [analyticsError, setAnalyticsError] = useState('')

  const categories = useMemo(() => {
    const values = new Set(products.map((product) => product.category))
    return ['all', ...Array.from(values)]
  }, [products])

  const cartProducts = useMemo(
    () =>
      products.filter((product) => cart[product.id]).map((product) => ({
        ...product,
        quantity: cart[product.id],
      })),
    [cart, products],
  )

  const cartTotal = cartProducts.reduce((total, item) => total + item.price * item.quantity, 0)

  const fetchProducts = async () => {
    try {
      setLoading(true)
      setProductsError('')
      const query = new URLSearchParams({ page: String(page), page_size: '8' })
      if (search) query.set('search', search)
      if (category && category !== 'all') query.set('category', category)
      const data = await fetchJson<{ items: Product[]; total_pages: number }>(`/api/products?${query.toString()}`)
      setProducts(data.items || [])
      setPageCount(data.total_pages || 1)
    } catch (error) {
      setProductsError(error instanceof Error ? error.message : 'Unable to load products')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchProducts()
  }, [search, category, page])

  useEffect(() => {
    if (!token) {
      setUser(null)
      localStorage.removeItem('saas-token')
      localStorage.removeItem('saas-user')
      return
    }

    const loadProfile = async () => {
      try {
        const profile = await fetchJson<User>('/api/users/me', {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        })
        setUser(profile)
        localStorage.setItem('saas-user', JSON.stringify(profile))
      } catch (error) {
        setToken('')
        setUser(null)
        localStorage.removeItem('saas-token')
        localStorage.removeItem('saas-user')
      }
    }

    void loadProfile()
  }, [token])

  useEffect(() => {
    if (!token || !user || user.role !== 'admin') {
      setAnalytics(null)
      return
    }

    const loadAnalytics = async () => {
      try {
        const data = await fetchJson<Analytics>('/api/admin/analytics', {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        })
        setAnalytics(data)
      } catch (error) {
        setAnalyticsError(error instanceof Error ? error.message : 'Unable to load analytics')
      }
    }

    void loadAnalytics()
  }, [token, user])

  const handleAuthSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setAuthError('')

    try {
      if (authMode === 'register') {
        await fetchJson('/api/auth/register', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            email: authForm.email,
            password: authForm.password,
          }),
        })
      }

      const loginResult = await fetchJson<{ access_token: string; user: User }>('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email: authForm.email,
          password: authForm.password,
        }),
      })

      localStorage.setItem('saas-token', loginResult.access_token)
      setToken(loginResult.access_token)
      setUser(loginResult.user)
      localStorage.setItem('saas-user', JSON.stringify(loginResult.user))
      setAuthForm({ email: '', password: '' })
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Authentication failed')
    }
  }

  const handleLogout = () => {
    setToken('')
    setUser(null)
    setAnalytics(null)
    localStorage.removeItem('saas-token')
    localStorage.removeItem('saas-user')
  }

  const addToCart = (productId: number) => {
    setCart((current) => ({
      ...current,
      [productId]: (current[productId] || 0) + 1,
    }))
  }

  const decreaseCartItem = (productId: number) => {
    setCart((current) => {
      const nextValue = (current[productId] || 0) - 1
      if (nextValue <= 0) {
        const next = { ...current }
        delete next[productId]
        return next
      }
      return { ...current, [productId]: nextValue }
    })
  }

  const submitCheckout = async () => {
    if (!token || cartProducts.length === 0) {
      return
    }

    try {
      const result = await fetchJson<{ order_id: number; total_amount: number; status: string }>(
        '/api/orders/checkout',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            items: cartProducts.map((item) => ({
              product_id: item.id,
              quantity: item.quantity,
            })),
          }),
        },
      )
      setCheckoutMessage(`Order ${result.order_id} created. Total: $${result.total_amount.toFixed(2)} (${result.status})`)
      setCart({})
    } catch (error) {
      setCheckoutMessage(error instanceof Error ? error.message : 'Checkout failed')
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">SaaS Dashboard</p>
          <h1>CloudFlow Analytics</h1>
        </div>

        <div className="auth-panel">
          {user ? (
            <>
              <span className="pill">{user.role}</span>
              <span>{user.email}</span>
              <button type="button" onClick={handleLogout} className="secondary-button">
                Logout
              </button>
            </>
          ) : (
            <form className="auth-form" onSubmit={handleAuthSubmit}>
              <input
                type="email"
                placeholder="Email"
                value={authForm.email}
                onChange={(event) => setAuthForm((current) => ({ ...current, email: event.target.value }))}
                required
              />
              <input
                type="password"
                placeholder="Password"
                value={authForm.password}
                onChange={(event) => setAuthForm((current) => ({ ...current, password: event.target.value }))}
                required
              />
              <button type="submit" className="primary-button">
                {authMode === 'login' ? 'Login' : 'Register'}
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => setAuthMode((current) => (current === 'login' ? 'register' : 'login'))}
              >
                {authMode === 'login' ? 'Need an account?' : 'Already registered?'}
              </button>
            </form>
          )}
        </div>
      </header>

      {authError ? <div className="alert error">{authError}</div> : null}

      <main className="layout">
        <section className="catalog-panel">
          <div className="toolbar">
            <input
              type="search"
              placeholder="Search products"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
              }}
            />
            <select value={category} onChange={(event) => { setCategory(event.target.value); setPage(1) }}>
              {categories.map((value) => (
                <option key={value} value={value}>
                  {value === 'all' ? 'All categories' : value}
                </option>
              ))}
            </select>
          </div>

          {loading ? (
            <div className="state-card">Loading products…</div>
          ) : productsError ? (
            <div className="state-card error">{productsError}</div>
          ) : products.length === 0 ? (
            <div className="state-card">No products match the current filters.</div>
          ) : (
            <div className="product-grid">
              {products.map((product) => (
                <article className="product-card" key={product.id}>
                  <span className="product-tag">{product.category}</span>
                  <h3>{product.name}</h3>
                  <p>{product.description}</p>
                  <div className="meta-row">
                    <strong>${product.price.toFixed(2)}</strong>
                    <span>{product.stock} in stock</span>
                  </div>
                  <button type="button" className="primary-button" onClick={() => addToCart(product.id)}>
                    Add to cart
                  </button>
                </article>
              ))}
            </div>
          )}

          <div className="pager">
            <button type="button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1}>
              Previous
            </button>
            <span>
              Page {page} / {pageCount || 1}
            </span>
            <button type="button" onClick={() => setPage((current) => current + 1)} disabled={page >= pageCount}>
              Next
            </button>
          </div>
        </section>

        <aside className="cart-panel">
          <h2>Checkout</h2>
          {cartProducts.length === 0 ? (
            <div className="empty-cart">Your cart is empty.</div>
          ) : (
            <div className="cart-list">
              {cartProducts.map((item) => (
                <div className="cart-item" key={item.id}>
                  <div>
                    <strong>{item.name}</strong>
                    <span>${item.price.toFixed(2)} each</span>
                  </div>
                  <div className="quantity-controls">
                    <button type="button" onClick={() => decreaseCartItem(item.id)}>-</button>
                    <span>{item.quantity}</span>
                    <button type="button" onClick={() => addToCart(item.id)}>+</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="checkout-total">
            <span>Total</span>
            <strong>${cartTotal.toFixed(2)}</strong>
          </div>

          <button
            type="button"
            className="primary-button wide"
            disabled={!token || cartProducts.length === 0}
            onClick={submitCheckout}
          >
            {token ? 'Complete checkout' : 'Login to checkout'}
          </button>
          {checkoutMessage ? <div className="alert info">{checkoutMessage}</div> : null}
        </aside>
      </main>

      {user?.role === 'admin' ? (
        <section className="analytics-panel">
          <h2>Admin analytics</h2>
          {analyticsError ? <div className="alert error">{analyticsError}</div> : null}
          {analytics ? (
            <>
              <div className="stats-grid">
                <div className="stat-box">
                  <span>Total sales</span>
                  <strong>${analytics.total_sales.toFixed(2)}</strong>
                </div>
                <div className="stat-box">
                  <span>User signups</span>
                  <strong>{analytics.user_signups}</strong>
                </div>
              </div>

              <div className="analytics-grid">
                <div className="summary-box">
                  <h3>Order logs</h3>
                  {analytics.order_logs.length === 0 ? (
                    <p>No orders yet.</p>
                  ) : (
                    <ul>
                      {(analytics.order_logs as Array<Record<string, any>>).map((log, index) => (
                        <li key={`${String(log.order_id)}-${index}`}>
                          #{String(log.order_id)} · {String(log.customer_email)} · {String(log.status)} · ${Number(log.total_amount).toFixed(2)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="summary-box">
                  <h3>Order status summary</h3>
                  {analytics.order_status_summary.length === 0 ? (
                    <p>No statuses recorded.</p>
                  ) : (
                    <ul>
                      {analytics.order_status_summary.map((row) => (
                        <li key={String(row.status)}>
                          {String(row.status)}: {String(row.count)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="summary-box">
                  <h3>Transaction status summary</h3>
                  {analytics.transaction_status_summary.length === 0 ? (
                    <p>No transactions yet.</p>
                  ) : (
                    <ul>
                      {analytics.transaction_status_summary.map((row) => (
                        <li key={String(row.status)}>
                          {String(row.status)}: {String(row.count)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="state-card">Loading analytics…</div>
          )}
        </section>
      ) : null}
    </div>
  )
}

export default App
