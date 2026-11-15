import { describe, expect, it } from 'vitest'
import { byUnit, money, pct, price, ratio } from '../lib/format'

describe('money', () => {
  it('shows Indian amounts in crore and lakh crore', () => {
    expect(money(5e9)).toBe('₹500 Cr')
    expect(money(8.71e12)).toBe('₹8.71 L Cr')
    expect(money(250_000)).toBe('₹2.50 L')
  })
  it('shows other currencies in K/M/B/T with their own symbol', () => {
    expect(money(3.2e12, 'USD')).toBe('$3.20T')
    expect(money(4.5e9, 'USD')).toBe('$4.50B')
    expect(money(-7.25e6, 'USD')).toBe('−$7.3M')
    expect(money(1e6, 'EUR')).toBe('EUR 1.0M')
  })
  it('never prints a number for missing data', () => {
    for (const v of [null, undefined, NaN, Infinity, '12']) expect(money(v)).toBe('—')
  })
})

describe('price, pct and ratio', () => {
  it('formats per-share prices with two decimals in the right grouping', () => {
    expect(price(1234567.5)).toBe('₹12,34,567.50')
    expect(price(1234567.5, 'USD')).toBe('$1,234,567.50')
  })
  it('uses a true minus sign and optional plus sign', () => {
    expect(pct(-3.14)).toBe('−3.1%')
    expect(pct(2, 0, true)).toBe('+2%')
    expect(ratio(-0.5)).toBe('−0.50×')
  })
})

describe('byUnit', () => {
  it('formats a metric by the unit the backend declares', () => {
    expect(byUnit(12.345, 'pct')).toBe('12.3%')
    expect(byUnit(1.5, 'x')).toBe('1.50×')
    expect(byUnit(45, 'days')).toBe('45 days')
    expect(byUnit(-2, 'pp')).toBe('-2.0 pp')
    expect(byUnit(0.42, 'share')).toBe('42%')
    expect(byUnit(99.5, 'per_share', 'USD')).toBe('$99.50')
    expect(byUnit(null, 'pct')).toBe('—')
  })
})
