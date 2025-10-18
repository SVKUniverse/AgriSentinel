/**
 * AgriSentinel Client-Side JavaScript
 * Handles map initialization, polygon capture, and API interactions
 */

// Global variables
let addParcelMapInstance = null;
let landDetailMapInstance = null;
let drawnItems = null;
let cornersRecorded = [];
let currentParcelGeometry = null;
let heatmapLayer = null;

/**
 * Initialize the "Add Parcel" map in the modal
 */
function initializeAddParcelMap() {
    if (addParcelMapInstance) {
        addParcelMapInstance.remove();
    }

    // Initialize map centered on a default location
    addParcelMapInstance = L.map('addParcelMap').setView([20.5937, 78.9629], 5);

    // Add base tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(addParcelMapInstance);

    // Add satellite layer option
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles © Esri',
        maxZoom: 19
    });

    // Layer control
    const baseMaps = {
        "Street Map": L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'),
        "Satellite": satellite
    };
    L.control.layers(baseMaps).addTo(addParcelMapInstance);

    // Initialize FeatureGroup for drawn items
    drawnItems = new L.FeatureGroup();
    addParcelMapInstance.addLayer(drawnItems);

    // Initialize Leaflet Draw controls
    const drawControl = new L.Control.Draw({
        draw: {
            polygon: {
                allowIntersection: false,
                showArea: true,
                shapeOptions: {
                    color: '#28a745',
                    weight: 2
                }
            },
            polyline: false,
            rectangle: false,
            circle: false,
            marker: false,
            circlemarker: false
        },
        edit: {
            featureGroup: drawnItems,
            remove: true
        }
    });
    addParcelMapInstance.addControl(drawControl);

    // Handle polygon creation
    addParcelMapInstance.on(L.Draw.Event.CREATED, function (event) {
        const layer = event.layer;
        drawnItems.clearLayers();
        drawnItems.addLayer(layer);
        
        // Store geometry
        currentParcelGeometry = layer.toGeoJSON().geometry;
        updateGeometryStatus(true);
        document.getElementById('saveParcelBtn').disabled = false;
    });

    // Handle polygon deletion
    addParcelMapInstance.on(L.Draw.Event.DELETED, function () {
        currentParcelGeometry = null;
        updateGeometryStatus(false);
        document.getElementById('saveParcelBtn').disabled = true;
    });

    // Reset corners when modal opens
    cornersRecorded = [];
    updateCornerCount();
    
    // Try to get user's location
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                addParcelMapInstance.setView([lat, lng], 15);
                L.marker([lat, lng]).addTo(addParcelMapInstance)
                    .bindPopup('Your Location')
                    .openPopup();
            },
            (error) => {
                console.log('Geolocation error:', error);
            }
        );
    }

    // Setup corner recording buttons
    setupCornerRecording();
}

/**
 * Setup corner recording functionality for mobile
 */
function setupCornerRecording() {
    const recordBtn = document.getElementById('recordCornerBtn');
    const finishBtn = document.getElementById('finishParcelBtn');
    const clearBtn = document.getElementById('clearCornersBtn');

    recordBtn.onclick = function() {
        if (!navigator.geolocation) {
            alert('Geolocation is not supported by your browser');
            return;
        }

        recordBtn.disabled = true;
        recordBtn.innerHTML = '📍 Getting location...';

        navigator.geolocation.getCurrentPosition(
            (position) => {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                
                cornersRecorded.push([lng, lat]); // GeoJSON format: [lng, lat]
                
                // Add marker to map
                L.marker([lat, lng]).addTo(addParcelMapInstance)
                    .bindPopup(`Corner ${cornersRecorded.length}`)
                    .openPopup();
                
                // Draw lines between corners
                if (cornersRecorded.length > 1) {
                    const latLngs = cornersRecorded.map(c => [c[1], c[0]]);
                    L.polyline(latLngs, {color: '#28a745', weight: 2}).addTo(addParcelMapInstance);
                }
                
                updateCornerCount();
                recordBtn.disabled = false;
                recordBtn.innerHTML = '📍 Record Corner';
                
                // Enable finish button if we have at least 3 corners
                if (cornersRecorded.length >= 3) {
                    finishBtn.disabled = false;
                }

                // Center map on last corner
                addParcelMapInstance.setView([lat, lng], 17);
            },
            (error) => {
                alert('Error getting location: ' + error.message);
                recordBtn.disabled = false;
                recordBtn.innerHTML = '📍 Record Corner';
            },
            {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 0
            }
        );
    };

    finishBtn.onclick = function() {
        if (cornersRecorded.length < 3) {
            alert('Need at least 3 corners to create a parcel');
            return;
        }

        // Close the polygon
        const polygonCoords = [...cornersRecorded, cornersRecorded[0]];
        
        // Create GeoJSON geometry
        currentParcelGeometry = {
            type: 'Polygon',
            coordinates: [polygonCoords]
        };

        // Draw the completed polygon
        drawnItems.clearLayers();
        const polygon = L.geoJSON(currentParcelGeometry, {
            style: {
                color: '#28a745',
                weight: 2,
                fillOpacity: 0.3
            }
        }).addTo(drawnItems);

        // Fit map to polygon bounds
        addParcelMapInstance.fitBounds(polygon.getBounds());

        updateGeometryStatus(true);
        document.getElementById('saveParcelBtn').disabled = false;
        finishBtn.disabled = true;
    };

    clearBtn.onclick = function() {
        cornersRecorded = [];
        drawnItems.clearLayers();
        currentParcelGeometry = null;
        updateCornerCount();
        updateGeometryStatus(false);
        finishBtn.disabled = true;
        document.getElementById('saveParcelBtn').disabled = true;
        
        // Remove all markers and polylines
        addParcelMapInstance.eachLayer(function(layer) {
            if (layer instanceof L.Marker || layer instanceof L.Polyline) {
                addParcelMapInstance.removeLayer(layer);
            }
        });
    };
}

/**
 * Update corner count display
 */
function updateCornerCount() {
    document.getElementById('cornerCount').textContent = cornersRecorded.length;
}

/**
 * Update geometry status message
 */
function updateGeometryStatus(hasGeometry) {
    const statusDiv = document.getElementById('geometryStatus');
    if (hasGeometry) {
        statusDiv.className = 'alert alert-success';
        statusDiv.innerHTML = '✓ Parcel boundary defined. Ready to save!';
    } else {
        statusDiv.className = 'alert alert-warning';
        statusDiv.innerHTML = 'ℹ️ Draw a polygon or record corners to define your parcel';
    }
}

/**
 * Save new parcel via API
 */
document.getElementById('saveParcelBtn')?.addEventListener('click', async function() {
    const name = document.getElementById('parcelName').value.trim();
    const description = document.getElementById('parcelDescription').value.trim();

    if (!name) {
        alert('Please enter a parcel name');
        return;
    }

    if (!currentParcelGeometry) {
        alert('Please draw or record a parcel boundary');
        return;
    }

    const saveBtn = this;
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Saving...';

    try {
        const response = await fetch('/api/lands', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: name,
                description: description,
                geojson: currentParcelGeometry
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to save parcel');
        }

        const result = await response.json();
        
        // Close modal and reload page
        bootstrap.Modal.getInstance(document.getElementById('addParcelModal')).hide();
        window.location.reload();

    } catch (error) {
        alert('Error saving parcel: ' + error.message);
        saveBtn.disabled = false;
        saveBtn.innerHTML = 'Save Parcel';
    }
});

/**
 * Initialize land detail map
 */
function initializeLandDetailMap() {
    if (!window.LAND_DATA) return;

    // Initialize map
    landDetailMapInstance = L.map('landMap').setView([0, 0], 2);

    // Add base layers
    const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(landDetailMapInstance);

    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles © Esri',
        maxZoom: 19
    });

    L.control.layers({
        "Street Map": street,
        "Satellite": satellite
    }).addTo(landDetailMapInstance);

    // Add parcel boundary
    const parcelLayer = L.geoJSON(window.LAND_DATA.geojson, {
        style: {
            color: '#28a745',
            weight: 3,
            fillOpacity: 0.1
        }
    }).addTo(landDetailMapInstance);

    // Fit map to parcel bounds
    landDetailMapInstance.fitBounds(parcelLayer.getBounds());

    // Setup analysis button
    document.getElementById('runAnalysisBtn').addEventListener('click', runAnalysis);

    // Setup download button
    document.getElementById('downloadGeoJsonBtn').addEventListener('click', downloadGeoJSON);

    // Load area
    loadParcelArea();
}

/**
 * Run crop health analysis
 */
async function runAnalysis() {
    const btn = document.getElementById('runAnalysisBtn');
    const btnText = document.getElementById('analysisBtnText');
    const spinner = document.getElementById('analysisSpinner');

    btn.disabled = true;
    btnText.classList.add('d-none');
    spinner.classList.remove('d-none');

    try {
        const response = await fetch(`/api/lands/${window.LAND_DATA.id}/compute`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error('Analysis failed');
        }

        const result = await response.json();
        
        // Display heatmap
        displayHeatmap(result.heatmap);
        
        // Update analytics
        updateAnalytics(result.stats);
        
        // Update last analysis time
        document.getElementById('lastAnalysisTime').textContent = 
            new Date(result.computed_at).toLocaleString();

        alert('Analysis complete! Check the Map and Analytics tabs.');

    } catch (error) {
        alert('Error running analysis: ' + error.message);
    } finally {
        btn.disabled = false;
        btnText.classList.remove('d-none');
        spinner.classList.add('d-none');
    }
}

/**
 * Display heatmap on map
 */
function displayHeatmap(heatmapGeoJSON) {
    // Remove existing heatmap layer
    if (heatmapLayer) {
        landDetailMapInstance.removeLayer(heatmapLayer);
    }

    // Add new heatmap layer
    heatmapLayer = L.geoJSON(heatmapGeoJSON, {
        style: function(feature) {
            return {
                fillColor: feature.properties.color,
                fillOpacity: 0.6,
                color: '#333',
                weight: 1
            };
        },
        onEachFeature: function(feature, layer) {
            const props = feature.properties;
            layer.bindPopup(`
                <h6>Health Zone</h6>
                <strong>Health Score:</strong> ${props.health_score}<br>
                <strong>Severity:</strong> ${props.severity}<br>
                <strong>Anomaly Score:</strong> ${props.anomaly_score}
            `);
        }
    }).addTo(landDetailMapInstance);
}

/**
 * Update analytics display
 */
function updateAnalytics(stats) {
    document.getElementById('totalZones').textContent = stats.total_zones;
    document.getElementById('healthyZones').textContent = stats.healthy_count;
    document.getElementById('warningZones').textContent = stats.warning_count + stats.moderate_count;
    document.getElementById('criticalZones').textContent = stats.critical_count;

    // Update progress bar
    const avgHealthPercent = Math.round(stats.avg_health * 100);
    const avgHealthBar = document.getElementById('avgHealthBar');
    avgHealthBar.style.width = avgHealthPercent + '%';
    avgHealthBar.textContent = avgHealthPercent + '%';
    
    // Change color based on health
    avgHealthBar.className = 'progress-bar';
    if (avgHealthPercent >= 70) {
        avgHealthBar.classList.add('bg-success');
    } else if (avgHealthPercent >= 50) {
        avgHealthBar.classList.add('bg-warning');
    } else {
        avgHealthBar.classList.add('bg-danger');
    }

    // Update message
    const message = document.getElementById('analyticsMessage');
    message.className = 'alert alert-info';
    message.innerHTML = `
        <strong>Analysis Summary:</strong><br>
        Average health score is ${avgHealthPercent}%. 
        ${stats.critical_count > 0 ? 
            `<br><strong class="text-danger">⚠️ ${stats.critical_count} critical zones detected requiring immediate attention!</strong>` : 
            'All zones are in acceptable condition.'}
    `;
}

/**
 * Download parcel GeoJSON
 */
function downloadGeoJSON() {
    const dataStr = JSON.stringify({
        type: 'Feature',
        properties: {
            name: window.LAND_DATA.name,
            id: window.LAND_DATA.id
        },
        geometry: window.LAND_DATA.geojson
    }, null, 2);
    
    const dataBlob = new Blob([dataStr], {type: 'application/json'});
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${window.LAND_DATA.name.replace(/\s+/g, '_')}_parcel.geojson`;
    link.click();
    URL.revokeObjectURL(url);
}

/**
 * Load and display parcel area
 */
async function loadParcelArea() {
    try {
        const response = await fetch(`/api/lands/${window.LAND_DATA.id}/area`);
        const data = await response.json();
        
        document.getElementById('areaDisplay').innerHTML = `
            ${data.area_hectares.toFixed(2)} hectares<br>
            <small>(${data.area_acres.toFixed(2)} acres)</small>
        `;
    } catch (error) {
        document.getElementById('areaDisplay').textContent = 'Error calculating area';
    }
}

/**
 * Utility: Format date
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}