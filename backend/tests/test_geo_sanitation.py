import json
from shapely.geometry import Polygon, mapping
from shapely.validation import make_valid

def test_bowtie_polygon():
    # A classic self-intersecting "bowtie" polygon
    # (0,0) -> (2,2) -> (2,0) -> (0,2) -> (0,0)
    bowtie_coords = [(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)]
    poly = Polygon(bowtie_coords)
    
    print(f"Is valid initially? {poly.is_valid}")
    assert not poly.is_valid, "Bowtie should be invalid"
    
    # Sanitize
    valid_poly = make_valid(poly)
    print(f"Is valid after make_valid? {valid_poly.is_valid}")
    assert valid_poly.is_valid, "Sanitized polygon should be valid"
    
    # Check GeoJSON structure via mapping
    geojson = mapping(valid_poly)
    print("Sanitized GeoJSON Type:", geojson['type'])
    # make_valid often turns a bowtie into a MultiPolygon of two triangles
    assert geojson['type'] in ["Polygon", "MultiPolygon"]
    
    # Verify closing ring logic (Shapely does this automatically, but good to check)
    if geojson['type'] == "Polygon":
        coords = geojson['coordinates'][0]
        assert coords[0] == coords[-1], "Polygon must be closed"
    elif geojson['type'] == "MultiPolygon":
        for poly_coords in geojson['coordinates']:
            assert poly_coords[0][0] == poly_coords[0][-1], "MultiPolygon rings must be closed"

    print("\nSUCCESS: Geo-sanitation (make_valid) resolved the bowtie into a valid indexable structure.")

if __name__ == "__main__":
    try:
        test_bowtie_polygon()
    except Exception as e:
        print(f"FAILED: {e}")
        exit(1)
