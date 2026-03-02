import AVFoundation

# Get all video devices
devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)

for device in devices:
    print(f"Name: {device.localizedName()}")
    print(f"UID: {device.uniqueID()}")
    print("-" * 20)
