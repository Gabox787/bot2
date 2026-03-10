def calculate_grid(current_price, step_pct, levels):
    buy_prices = []
    sell_prices = []
    
    for i in range(1, levels + 1):
        # Рассчитываем цены покупки ниже текущей
        buy_price = current_price * (1 - (step_pct * i) / 100)
        buy_prices.append(round(buy_price, 2))
        
        # Рассчитываем цены продажи выше текущей
        sell_price = current_price * (1 + (step_pct * i) / 100)
        sell_prices.append(round(sell_price, 2))
        
    return buy_prices, sell_prices
