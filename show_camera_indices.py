import cv2
import sys
import os

def capture_and_label_cameras():
    print("=" * 60)
    print("CAMERA INDEX IDENTIFICATION TOOL")
    print("=" * 60)
    
    # Create output directory
    output_dir = "camera_indices_check"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    # Use appropriate backend
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    
    found_cameras = []
    
    # Check indices 0-9
    for i in range(10):
        print(f"Checking index {i}...", end="", flush=True)
        try:
            cap = cv2.VideoCapture(i, backend)
            
            if not cap.isOpened():
                print(" Not available.")
                continue
                
            # Try to read a frame
            ret, frame = cap.read()
            
            if ret:
                height, width = frame.shape[:2]
                text = f"Camera Index: {i}"
                
                # Draw black background rectangle for text
                font_scale = 2.0
                thickness = 3
                font = cv2.FONT_HERSHEY_SIMPLEX
                (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
                
                # Ensure rectangle is within frame
                rect_start = (50, 50)
                rect_end = (50 + text_w + 20, 50 + text_h + 40)
                
                # Draw filled rectangle for background
                cv2.rectangle(frame, rect_start, rect_end, (0, 0, 0), -1)
                
                # Draw text
                text_pos = (60, 50 + text_h + 10)
                cv2.putText(frame, text, text_pos, font, font_scale, (0, 255, 0), thickness)
                
                filename = os.path.join(output_dir, f"camera_index_{i}.jpg")
                cv2.imwrite(filename, frame)
                print(f" CAPTURED -> Saved to {filename}")
                found_cameras.append(i)
                cap.release()
            else:
                print(" Opened but failed to read frame.")
                cap.release()
        except Exception as e:
            print(f" Error: {e}")
            
    print("-" * 60)
    if found_cameras:
        print(f"Successfully captured images for indices: {found_cameras}")
        print(f"Check the '{output_dir}' folder to identify your cameras.")
        
        # Try to open the folder (Mac specific)
        if sys.platform == "darwin":
            os.system(f"open {output_dir}")
    else:
        print("No cameras could be read.")
    print("=" * 60)

if __name__ == "__main__":
    capture_and_label_cameras()
