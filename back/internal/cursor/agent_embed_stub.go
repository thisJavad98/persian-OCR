//go:build !vercel

package cursor

func embeddedBundleBytes() []byte {
	return nil
}