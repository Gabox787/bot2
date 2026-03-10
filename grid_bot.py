import config
from grid_logic import calculate_grid

def main():
    print(f"--- Запуск Grid-бота для {config.SYMBOL} ---")
    
    # Имитируем получение текущей цены (позже заменим на запрос к API)
    mock_price = 65000.0 
    
    buys, sells = calculate_grid(mock_price, config.GRID_STEP, config.GRID_LEVELS)
    
    print(f"Текущая цена: {mock_price}")
    print("\nОрдера на ПРОДАЖУ (выше цены):")
    for s in reversed(sells):
        print(f"  [ SELL ] {s} USDT")
        
    print("------- ЦЕНА СЕЙЧАС -------")
    
    print("Ордера на ПОКУПКУ (ниже цены):")
    for b in buys:
        print(f"  [ BUY  ] {b} USDT")

if __name__ == "__main__":
    main()
