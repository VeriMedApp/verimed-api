"""
PWA Icon Generator for ProofMed
Generates 192x192 and 512x512 icons from the official logo
"""
from PIL import Image
import os

def generate_pwa_icons():
    """Generate PWA icons from the official logo"""
    
    # Source logo
    source_logo = "branding/logo.png"
    
    if not os.path.exists(source_logo):
        print(f"ERROR: {source_logo} not found!")
        return
    
    # Load the original logo
    img = Image.open(source_logo)
    print(f"Loaded original logo: {img.size[0]}x{img.size[1]} px")
    
    # Define output paths and sizes
    icons = [
        ("branding/icon-192.png", 192),
        ("branding/icon-512.png", 512),
        ("app/static/branding/logo.png", img.size[0]),  # Copy original
        ("app/static/branding/icon-192.png", 192),
        ("app/static/branding/icon-512.png", 512),
    ]
    
    # Ensure directories exist
    os.makedirs("branding", exist_ok=True)
    os.makedirs("app/static/branding", exist_ok=True)
    
    # Generate each icon
    for output_path, size in icons:
        if size == img.size[0]:
            # Copy original without resizing
            img.save(output_path, "PNG", quality=100, optimize=True)
            print(f"Copied: {output_path}")
        else:
            # Resize with high-quality Lanczos filter
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(output_path, "PNG", quality=100, optimize=True)
            print(f"Generated: {output_path} ({size}x{size})")
    
    print("\nAll PWA icons generated successfully!")

if __name__ == "__main__":
    generate_pwa_icons()
