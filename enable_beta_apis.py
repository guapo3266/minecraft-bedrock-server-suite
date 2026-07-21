import amulet_nbt
import os
import sys

def enable_beta_apis(level_dat_path):
    if not os.path.exists(level_dat_path):
        print(f"File not found: {level_dat_path}")
        sys.exit(1)
        
    print(f"Loading {level_dat_path}...")
    level_data = amulet_nbt.load(level_dat_path)
    
    experiments = level_data.get('experiments')
    if experiments is None:
        experiments = amulet_nbt.TAG_Compound()
        level_data['experiments'] = experiments
        print("Created new experiments compound.")
        
    # Enable Beta APIs and custom components
    experiments['gametest'] = amulet_nbt.TAG_Byte(1)
    experiments['data_driven_items'] = amulet_nbt.TAG_Byte(1)
    experiments['experimental_custom_ui'] = amulet_nbt.TAG_Byte(1)
    experiments['experiments_ever_used'] = amulet_nbt.TAG_Byte(1)
    experiments['saved_with_toggled_experiments'] = amulet_nbt.TAG_Byte(1)
    
    print("Injected experiment tags.")
    
    # Save the modified level.dat
    level_data.save_to(level_dat_path)
    print("Saved modified level.dat successfully.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python enable_beta_apis.py <ruta_a_level.dat>")
        sys.exit(1)
    enable_beta_apis(sys.argv[1])
